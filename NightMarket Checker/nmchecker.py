from time import sleep
import requests
import json
import re
import urllib3
import csv
import logging
import os
import cloudscraper
import sqlite3

# CONFIG
ENABLE_NIGHTMARKET = False
OUTPUT_NIGHTMARKET_FILENAME = 'night_market.csv'
ENABLE_CURRENT_OFFER = True
OUTPUT_CURRENT_OFFER_FILENAME = 'current_offers.csv'
ENABLE_CACHE = False

logging.basicConfig(level=logging.INFO)


class db():
    def __init__(self) -> None:
        db.database = sqlite3.connect('data.db', check_same_thread=False)
        db.cur = db.database.cursor()

    def kill(self) -> None:
        db.database.commit()
        db.database.close()

    def commit(self) -> bool:
        success = False
        try:
            db.database.commit()
            success = True
        except Exception as err:
            logging.error(err)
        finally:
            return success

    def create_database(self) -> None:
        try:
            db.cur.execute('''CREATE TABLE valorant_offers
            (
                id  INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                offer_id    TEXT,
                price   INT,
                item_type_id    TEXT,
                item_id TEXT,
                start_date  TEXT
            )''')
        except Exception as err:
            logging.error(err)

    def truncate_table(self, table) -> None:
        logging.debug('Truncate table : {}'.format(table))
        db.cur.execute('DELETE FROM {} WHERE 1=1'.format(table))
        self.commit()

    @staticmethod
    def get_skin_name(skinid) -> str:
        response = requests.get(
            'https://valorant-api.com/v1/weapons/skinlevels/{}'.format(skinid))
        if (response.status_code == 200):
            _res = response.json()
            return _res['data']['displayName']
        else:
            return ''

    def cache_valorant_offers(self, data: dict, truncate: bool = False) -> None:
        if truncate:
            self.truncate_table(table='valorant_offers')

        for offer in data['Offers']:
            _cost = offer['Cost']['85ad13f7-3d1b-5128-9eb2-7cd8ee0b5741']
            _offerId = offer['OfferID']
            _startDate = offer['StartDate']
            _itemId = offer['Rewards'][0]['ItemID']
            _itemTypeId = offer['Rewards'][0]['ItemTypeID']
            _name = self.get_skin_name(_itemId).replace("'", "''")

            logging.debug('Caching item: id: {}, name: {}, cost: {}'.format(
                _itemId, _name, _cost))
            _query = '''INSERT INTO valorant_offers (offer_id, price, item_type_id, item_id, start_date, name) VALUES ('{}', {}, '{}', '{}', '{}', '{}')'''.format(
                _offerId, str(_cost), _itemTypeId, _itemId, _startDate, _name)
            logging.debug('Query: {}'.format(_query))
            db.cur.execute(_query)
        self.commit()

    def update_item_name(self, item_name: str, item_id: str) -> None:
        logging.debug('Update item name {} -> {}'.format(item_id, item_name))
        db.cur.execute('''UPDATE valorant_offers
                        SET name = '{}'
                        WHERE item_id = '{}'
        '''.format(item_name, item_id))

    def get_offer_detail(self, offer_id: str):
        q = db.cur.execute(
            "SELECT name, price FROM valorant_offers WHERE offer_id = '{}' LIMIT 1".format(offer_id))
        q = [x for x in q][0]
        logging.debug('Query for offer_id {} -> {}'.format(offer_id, q[0]))
        return q

    def get_item_name(self, item_id: str) -> str:
        q = db.cur.execute(
            "SELECT name FROM valorant_offers WHERE item_id = '{}' LIMIT 1".format(item_id))
        q = [x for x in q][0]
        return q[0]


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CURRENT_DIRECTORY = os.path.join(os.getcwd(), 'NightMarket Checker')

with open(os.path.join(CURRENT_DIRECTORY, "info.gg"), encoding='utf-8') as f:
    x = f.readline().rstrip("\n").split("=")
region = str(x[1])


def getCookie():
    headers = {}
    headers['Content-Type'] = 'application/json'
    headers['user-agent'] = 'RiotClient/43.0.1.4195386.4190634 rso-auth (Windows;10;;Professional, x64)'
    body = json.dumps({"client_id": "play-valorant-web-prod", "nonce": "1", "redirect_uri": "https://playvalorant.com/opt_in", "response_type": "token id_token", "scope": "account openid"
                       })
    retry = True
    while retry:
        global sess
        sess = requests.Session()
        global scraper
        scraper = cloudscraper.create_scraper(sess=sess, debug=False)
        response = scraper.post(
            "https://auth.riotgames.com/api/v1/authorization", data=body, headers=headers)
        if (response.status_code == 200):
            retry = False
            try:
                return(response.json())
            except json.decoder.JSONDecodeError as err:
                pass
        else:
            logging.info('Got caught by Cloudflare senpai... retrying ')
            sleep(2)


def getToken(username, password):
    headers = {}
    data = json.dumps({
        "type": "auth",
        "username": username,
        "password": password,
        "remember": False,
        "language": "en_US"
    })
    headers['Content-Type'] = 'application/json'
    headers['user-agent'] = 'RiotClient/43.0.1.4195386.4190634 rso-auth (Windows;10;;Professional, x64)'
    try:
        response = scraper.put(
            "https://auth.riotgames.com/api/v1/authorization", data=data, headers=headers)
        cap = response.json()
        ggwp = re.split('#|&', cap['response']['parameters']['uri'])
        ggez = (ggwp[1]).split("=")
        return (str(ggez[1]))
    except KeyError:
        logging.error("Credentials Invalid : {}".format(username))
        exit()


def getEntitle(token):
    headers = {}
    headers['Authorization'] = 'Bearer '+token
    headers['Content-Type'] = 'application/json'
    headers['user-agent'] = 'RiotClient/43.0.1.4195386.4190634 rso-auth (Windows;10;;Professional, x64)'
    response = scraper.post(
        "https://entitlements.auth.riotgames.com/api/token/v1", headers=headers)
    ggwp = response.json()
    headers['X-Riot-Entitlements-JWT'] = ggwp["entitlements_token"]

    return(headers)


def getPuuid(headers):
    response = scraper.get(
        "https://auth.riotgames.com/userinfo", headers=headers)
    ggwp = response.json()
    ggez = ggwp['sub']

    return ([ggez, headers])


# urggg idk if this works or not
def getNight(puid, headers, db: db):
    price = []
    skin = []
    response = scraper.get("https://pd.{region}.a.pvp.net/store/v2/storefront/{puuid}".format(
        puuid=puid, region=region), headers=headers)
    ggwp = response.json()
    for i in ggwp['BonusStore']['BonusStoreOffers']:
        [price.append(k) for k in i['DiscountCosts'].values()]

    for i in ggwp['BonusStore']['BonusStoreOffers']:
        [skin.append(db.get_item_name(k['ItemID']))
         for k in i['Offer']['Rewards']]

    return getSkinPrice(skin, price)


def get_current_offer(puid, headers, db: db):
    price = []
    skin = []
    response = scraper.get("https://pd.{region}.a.pvp.net/store/v2/storefront/{puuid}".format(
        puuid=puid, region=region), headers=headers)
    ggwp = response.json()

    for item in ggwp['SkinsPanelLayout']['SingleItemOffers']:
        _q = db.get_offer_detail(item)
        price.append(_q[1])
        skin.append(_q[0])

    return getSkinPrice(skin, price)


def cacheOffers(headers, db: db) -> None:
    response = scraper.get(
        'https://pd.{region}.a.pvp.net/store/v1/offers/'.format(region=region), headers=headers)
    db.cache_valorant_offers(response.json(), truncate=True)


def getSkinPrice(skin, price):
    both = []
    print(dict(zip(skin, price)))
    [both.append((str(skin[i])+":"+str(price[i]))) for i in range(len(skin))]

    return (both)


def csvWrite(all, file_name: str):
    with open(file_name, 'a+', newline="\n") as csvfile:
        write = csv.writer(csvfile)
        topcol = ['Account', 'Offer1', 'Offer2',
                  'Offer3', 'Offer4', 'Offer5', 'Offer6']
        write.writerow(topcol)
        for i in all:
            write.writerow(i)
        write.writerow("\n")
        print("-"*50)
        print("Saved all accounts informations in {}".format(file_name))


def main():
    if ENABLE_CACHE:
        cache = True
    else:
        cache = False
    database = db()
    database.create_database()
    all_current_offers = []
    all_night_market = []
    print("-"*150)
    with open(os.path.join(CURRENT_DIRECTORY, "accounts.txt"), encoding='utf-8') as f:
        for i in f.readlines():
            acc = i.rstrip("\n").split(";")
            getCookie()
            print(acc[0], end=" ")
            token = getToken(acc[0], acc[1])
            entitle = getEntitle(token)
            puuid = getPuuid(entitle)
            if cache:
                cacheOffers(puuid[1], db=database)
                cache = False

            if ENABLE_CURRENT_OFFER:
                price = get_current_offer(puuid[0], puuid[1], database)
                price.insert(0, acc[0])
                all_current_offers.append(price)
            if ENABLE_NIGHTMARKET:
                price = getNight(puuid[0], puuid[1])
                price.insert(0, acc[0])
                all_night_market.append(price)

    if ENABLE_CURRENT_OFFER:
        csvWrite(all_current_offers, OUTPUT_CURRENT_OFFER_FILENAME)
    if ENABLE_NIGHTMARKET:
        csvWrite(all_night_market, OUTPUT_NIGHTMARKET_FILENAME)


if __name__ == "__main__":
    main()
