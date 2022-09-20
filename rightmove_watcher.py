'''Rightmove web scraper'''

import json
import time
import pickle

from pathlib import Path
from typing import List
from collections import deque

import requests

from bs4 import BeautifulSoup
from twilio.rest import Client


def get_twilio_creds():
    '''Gets Twilio Credentials'''
    fpath = Path.home().joinpath('.twilio_cred')
    with open(fpath, 'r', encoding='utf-8') as f:
        creds = json.load(f)
    return creds


def get_search_params():
    '''Gets rightmove search paramaters'''
    fpath = Path.home().joinpath('.rightmove_params')
    with open(fpath, 'r', encoding='utf-8') as f:
        params = json.load(f)
    return params


def get_property_list(html_doc: str) -> List[str]:
    '''Returns list of properties found in search results

    Args:
        html_doc: html string

    Returns:
        property_ids: property ID list
    '''
    soup = BeautifulSoup(html_doc, 'html.parser')
    search_results = soup.find(id='l-searchResults')
    property_elems = search_results.findChildren('div', recursive=False)
    property_ids = [prop.get('id') for prop in property_elems]

    return property_ids


class RightMoveWatcher:
    '''Watches RightMove for updates'''

    def __init__(self, interval=300):
        self.root_url = 'https://rightmove.co.uk'
        self.search_url = '/'.join((self.root_url, 'property-to-rent', 'find.html'))
        self.sess = requests.Session()
        self.interval = interval
        self._property_id_fpath = Path.home().joinpath('.rightmove')
        self.property_ids = self._get_previous_property_list()
        self.twilio_creds = get_twilio_creds()
        self.check_depth = 10
        self.max_len = 75
        self._new = False
        self.fail_thresh = 3
        self._fail_count = 0

    def login(self, user, passw):
        '''Authenticates with RightMove'''
        res = self.sess.post(self.root_url, data={'email': user, 'password': passw})
        if res.status_code != 200:
            raise RuntimeError(f'Error in authenticating: {res.status_code}')

    def _get_previous_property_list(self):
        if self._property_id_fpath.exists():
            with open(self._property_id_fpath, 'rb') as fobj:
                return deque(pickle.load(fobj))
        return deque()

    def _save_property_list(self, property_ids):
        with open(self._property_id_fpath, 'wb') as fobj:
            pickle.dump(property_ids, fobj)

    def _add_properties_to_list(self, new_properties):
        for prop in new_properties:
            if prop not in self.property_ids:
                self.property_ids.appendleft(prop)
                if len(self.property_ids) > self.max_len:
                    self.property_ids.pop()

    def _get_search_results(self):
        try:
            res = self.sess.post(self.search_url, params=get_search_params())
            if res.status_code != 200:
                raise RuntimeError(f'Error in search: {res.status_code}')
            property_ids = get_property_list(res.text)
            self._fail_count = 0
            self._save_property_list(property_ids)
            return property_ids
        except requests.exceptions.ConnectionError:
            self._fail_count += 1
            print('Failed to connect.')
            if self._fail_count > self.fail_thresh:
                self.send_text('Script failed to connect.')
            return self.property_ids

    def send_text(self, msg):
        '''Sends text notification'''
        try:
            client = Client(self.twilio_creds['user'], self.twilio_creds['pass'])
            message = client.messages.create(
                body=msg, from_=self.twilio_creds['from_num'], to=self.twilio_creds['to_num']
            )
            print(f'SMS sent, ID: {message.sid}')
        except requests.exceptions.ConnectionError:
            print('Failed to send text :(')

    def watch(self):
        '''Watches RightMove search page'''
        while True:
            if len(self.property_ids) == 0:
                self.property_ids = deque(self._get_search_results())
                print(f'{len(self.property_ids)} initial properties.')
            else:
                new_properties = self._get_search_results()
                for idx in range(self.check_depth):
                    prop_id = new_properties[idx]
                    if prop_id not in self.property_ids:
                        print(f'*** New Property: {prop_id} ***')
                        self.send_text(f'New Property: {prop_id}')
                        self._new = True
                self._add_properties_to_list(new_properties)
                if self._new:
                    self._new = False
                else:
                    print('No new properties.')
            time.sleep(self.interval)


if __name__ == '__main__':
    watcher = RightMoveWatcher()
    watcher.watch()
