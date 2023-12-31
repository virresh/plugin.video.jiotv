# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os

import urlquick
from uuid import uuid4
import base64
import hashlib
import time
from functools import wraps
from distutils.version import LooseVersion
from codequick import Script
from codequick.storage import PersistentDict
from xbmc import executebuiltin
from xbmcgui import Dialog, DialogProgress
from xbmcaddon import Addon
import xbmc
import xbmcvfs
from contextlib import contextmanager
from collections import defaultdict
import socket
import json

from resources.lib.constants import CHANNELS_SRC, DICTIONARY_URL, FEATURED_SRC


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        s.connect(("8.8.8.8", 80))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP


def isLoggedIn(func):
    """
    Decorator to ensure that a valid login is present when calling a method
    """
    @wraps(func)
    def login_wrapper(*args, **kwargs):
        with PersistentDict("localdb") as db:
            username = db.get("username")
            password = db.get("password")
            headers = db.get("headers")
            exp = db.get("exp", 0)
        if headers and exp > time.time():
            return func(*args, **kwargs)
        elif username and password:
            login(username, password)
            return func(*args, **kwargs)
        elif headers and exp < time.time():
            Script.notify(
                "Login Error", "Session expired. Please login again")
            executebuiltin(
                "RunPlugin(plugin://plugin.video.jiotv/resources/lib/main/login/)")
            return False
        else:
            Script.notify(
                "Login Error", "You need to login with Jio Username and password to use this add-on")
            executebuiltin(
                "RunPlugin(plugin://plugin.video.jiotv/resources/lib/main/login/)")
            return False
    return login_wrapper


def login(username, password, mode="unpw"):
    resp = None
    if (mode == 'otp'):
        mobile = "+91" + username
        otpbody = {
            "number": base64.b64encode(mobile.encode("ascii")).decode("ascii"),
            "otp": password,
            "deviceInfo": {
                "consumptionDeviceName": "unknown sdk_google_atv_x86",
                "info": {
                    "type": "android",
                    "platform": {
                        "name": "generic_x86"
                    },
                    "androidId": str(uuid4())
                }
            }
        }
        resp = urlquick.post("https://jiotvapi.media.jio.com/userservice/apis/v1/loginotp/verify", json=otpbody, headers={
            "User-Agent": "okhttp/4.2.2", "devicetype": "phone", "os": "android", "appname": "RJIL_JioTV"}, max_age=-1, verify=False, raise_for_status=False).json()
    else:
        body = {
            "identifier": username if '@' in username else "+91" + username,
            "password": password,
            "rememberUser": "T",
            "upgradeAuth": "Y",
            "returnSessionDetails": "T",
            "deviceInfo": {
                "consumptionDeviceName": "ZUK Z1",
                "info": {
                    "type": "android",
                    "platform": {
                        "name": "ham",
                        "version": "8.0.0"
                    },
                    "androidId": str(uuid4())
                }
            }
        }
        resp = urlquick.post("https://api.jio.com/v3/dip/user/{0}/verify".format(mode), json=body, headers={
            "User-Agent": "JioTV", "x-api-key": "l7xx75e822925f184370b2e25170c5d5820a", "Content-Type": "application/json"}, max_age=-1, verify=False, raise_for_status=False).json()
    if resp.get("ssoToken", "") != "":
        _CREDS = {
            "ssotoken": resp.get("ssoToken"),
            "userid": resp.get("sessionAttributes", {}).get("user", {}).get("uid"),
            "uniqueid": resp.get("sessionAttributes", {}).get("user", {}).get("unique"),
            "crmid": resp.get("sessionAttributes", {}).get("user", {}).get("subscriberId"),
            "subscriberid": resp.get("sessionAttributes", {}).get("user", {}).get("subscriberId"),
        }
        headers = {
            "deviceId": str(uuid4()),
            "devicetype": "phone",
            "os": "android",
            "osversion": "9",
            "user-agent": "plaYtv/7.0.8 (Linux;Android 9) ExoPlayerLib/2.11.7",
            "usergroup": "tvYR7NSNn7rymo3F",
            "versioncode": "289",
            "dm": "ZUK ZUK Z1"
        }
        headers.update(_CREDS)
        with PersistentDict("localdb") as db:
            db["headers"] = headers
            # db["exp"] = time.time() + 432000
            db["exp"] = time.time() + 31536000
            if mode == "unpw":
                db["exp"] = time.time() + 432000
                db["username"] = username
                db["password"] = password
        Script.notify("Login Success", "")
        return None
    else:
        Script.log(resp, lvl=Script.INFO)
        msg = resp.get("message", "Unknow Error")
        Script.notify("Login Failed", msg)
        return msg


def sendOTPV2(mobile):
    if "+91" not in mobile:
        mobile = "+91" + mobile
    body = {"number": base64.b64encode(mobile.encode("ascii")).decode("ascii")}
    Script.log(body, lvl=Script.ERROR)
    resp = urlquick.post("https://jiotvapi.media.jio.com/userservice/apis/v1/loginotp/send", json=body, headers={
        "user-agent": "okhttp/4.2.2", "os": "android", "host": "jiotvapi.media.jio.com", "devicetype": "phone", "appname": "RJIL_JioTV"}, max_age=-1, verify=False, raise_for_status=False)
    if resp.status_code != 204:
        return resp.json().get("errors", [{}])[-1].get("message")
    return None


def logout():
    with PersistentDict("localdb") as db:
        del db["headers"]
    Script.notify("You\'ve been logged out", "")


def getHeaders():
    with PersistentDict("localdb") as db:
        return db.get("headers", False)


def getCachedChannels():
    with PersistentDict("localdb") as db:
        channelList = db.get("channelList", False)
        if not channelList:
            try:
                channelListResp = urlquick.get(
                    CHANNELS_SRC, verify=False).json().get("result")
                db["channelList"] = channelListResp
            except:
                Script.notify("Connection error ", "Retry after sometime")
        return db.get("channelList", False)


def getCachedDictionary():
    with PersistentDict("localdb") as db:
        dictionary = db.get("dictionary", False)
        if not dictionary:
            try:
                r = urlquick.get(DICTIONARY_URL, verify=False).text.encode(
                    'utf8')[3:].decode('utf8')
                db["dictionary"] = json.loads(r)
            except:
                Script.notify("Connection error ", "Retry after sometime")
        return db.get("dictionary", False)


def getFeatured():
    try:
        resp = urlquick.get(FEATURED_SRC, verify=False, headers={
            "usergroup": "tvYR7NSNn7rymo3F",
            "os": "android",
            "devicetype": "phone",
            "versionCode": "290"
        }, max_age=-1).json()
        return resp.get("featuredNewData", [])
    except:
        Script.notify("Connection error ", "Retry after sometime")


def cleanLocalCache():
    try:
        with PersistentDict("localdb") as db:
            del db["channelList"]
            del db["dictionary"]
    except:
        Script.notify("Cache", "Cleaned")


def getChannelHeaders():
    headers = getHeaders()
    return {
        'ssotoken': headers['ssotoken'],
        'userId': headers['userid'],
        'uniqueId': headers['uniqueid'],
        'crmid': headers['crmid'],
        'user-agent': 'plaYtv/7.0.8 (Linux;Android 9) ExoPlayerLib/2.11.7',
        'deviceid': headers['deviceId'],
        'devicetype': 'phone',
        'os': 'android',
        'osversion': '9',
    }


def getChannelHeadersWithHost():
    return {
        'deviceType': 'phone',
        'host': 'tv.media.jio.com',
        'os': 'android',
        'versioncode': '296',
        'Conetent-Type': 'application/json'
    }


def getTokenParams():
    def magic(x): return base64.b64encode(hashlib.md5(x.encode()).digest()).decode().replace(
        '=', '').replace('+', '-').replace('/', '_').replace('\r', '').replace('\n', '')
    pxe = str(int(time.time()+(3600*9.2)))
    jct = magic("cutibeau2ic9p-O_v1qIyd6E-rf8_gEOQ"+pxe)
    return {"jct": jct, "pxe": pxe, "st": "9p-O_v1qIyd6E-rf8_gEOQ"}


def check_addon(addonid, minVersion=False):
    """Checks if selected add-on is installed."""
    try:
        curVersion = Script.get_info("version", addonid)
        # Script.notify("version" , curVersion)
        if minVersion and LooseVersion(curVersion) < LooseVersion(minVersion):
            Script.log('{addon} {curVersion} doesn\'t setisfy required version {minVersion}.'.format(
                addon=addonid, curVersion=curVersion, minVersion=minVersion))
            Dialog().ok("Error", "{minVersion} version of {addon} is required to play this content.".format(
                addon=addonid, minVersion=minVersion))
            return False
        return True
    except RuntimeError:
        Script.log('{addon} is not installed.'.format(addon=addonid))
        if not _install_addon(addonid):
            # inputstream is missing on system
            Dialog().ok("Error",
                        "[B]{addon}[/B] is missing on your Kodi install. This add-on is required to play this content.".format(addon=addonid))
            return False
        return True


def _install_addon(addonid):
    """Install addon."""
    try:
        # See if there's an installed repo that has it
        executebuiltin('InstallAddon({})'.format(addonid), wait=True)

        # Check if add-on exists!
        version = Script.get_info("version", addonid)

        Script.log(
            '{addon} {version} add-on installed from repo.'.format(addon=addonid, version=version))
        return True
    except RuntimeError:
        Script.log('{addon} add-on not installed.'.format(addon=addonid))
        return False

<<<<<<< HEAD
=======

>>>>>>> 0838c8b307651a6527aaaea4e75dfaa3db8f886a
def quality_to_enum(quality_str, arr_len):
    """Converts quality into a numeric value. Max clips to fall within valid bounds."""
    mapping = {
        'Best': arr_len-1,
<<<<<<< HEAD
        'Low': 0,
        'Medium': max(1, arr_len-3),
        'High': max(2, arr_len-2)
=======
        'High': max(arr_len-2, arr_len-3),
        'Medium+': max(arr_len-3, arr_len-4),
        'Medium': max(2, arr_len-3),
        'Low': min(2, arr_len-3),
        'Lower': 1,
        'Lowest': 0,
>>>>>>> 0838c8b307651a6527aaaea4e75dfaa3db8f886a
    }
    if quality_str in mapping:
        return min(mapping[quality_str], arr_len-1)
    return 0
<<<<<<< HEAD
=======


_signals = defaultdict(list)
_skip = defaultdict(int)


def emit(signal, *args, **kwargs):
    if _skip[signal] > 0:
        _skip[signal] -= 1
        return

    for f in _signals.get(signal, []):
        f(*args, **kwargs)


class Monitor(xbmc.Monitor):
    def onSettingsChanged(self):
        emit('on_settings_changed')


monitor = Monitor()


def kodi_rpc(method, params=None, raise_on_error=False):
    try:
        payload = {'jsonrpc': '2.0', 'id': 1}
        payload.update({'method': method})
        if params:
            payload['params'] = params

        data = json.loads(xbmc.executeJSONRPC(json.dumps(payload)))
        if 'error' in data:
            raise Exception('Kodi RPC "{} {}" returned Error: "{}"'.format(
                method, params or '', data['error'].get('message')))

        return data['result']
    except Exception as e:
        if raise_on_error:
            raise
        else:
            return {}


def set_kodi_setting(key, value):
    return kodi_rpc('Settings.SetSettingValue', {'setting': key, 'value': value})


def same_file(path_a, path_b):
    if path_a.lower().strip() == path_b.lower().strip():
        return True

    stat_a = os.stat(path_a) if os.path.isfile(path_a) else None
    if not stat_a:
        return False

    stat_b = os.stat(path_b) if os.path.isfile(path_b) else None
    if not stat_b:
        return False

    return (stat_a.st_dev == stat_b.st_dev) and (stat_a.st_ino == stat_b.st_ino) and (stat_a.st_mtime == stat_b.st_mtime)


def safe_copy(src, dst, del_src=False):
    src = xbmcvfs.translatePath(src)
    dst = xbmcvfs.translatePath(dst)

    if not xbmcvfs.exists(src) or same_file(src, dst):
        return

    if xbmcvfs.exists(dst):
        if xbmcvfs.delete(dst):
            Script.log('Deleted: {}'.format(dst))
        else:
            Script.log('Failed to delete: {}'.format(dst))

    if xbmcvfs.copy(src, dst):
        Script.log('Copied: {} > {}'.format(src, dst))
    else:
        Script.log('Failed to copy: {} > {}'.format(src, dst))

    if del_src:
        xbmcvfs.delete(src)


@contextmanager
def busy():
    xbmc.executebuiltin('ActivateWindow(busydialognocancel)')
    try:
        yield
    finally:
        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')


def _setup(m3uPath, epgUrl):
    pDialog = DialogProgress()
    pDialog.create('PVR Setup in progress')
    ADDON_ID = 'pvr.iptvsimple'
    addon = Addon(ADDON_ID)
    ADDON_NAME = addon.getAddonInfo('name')
    addon_path = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    instance_filepath = os.path.join(addon_path, 'instance-settings-91.xml')

    kodi_rpc('Addons.SetAddonEnabled', {
        'addonid': ADDON_ID, 'enabled': False})
    pDialog.update(10)

    # newer PVR Simple uses instance settings that can't yet be set via python api
    # so do a workaround where we leverage the migration when no instance settings found
    if LooseVersion(addon.getAddonInfo('version')) >= LooseVersion('20.8.0'):
        xbmcvfs.delete(instance_filepath)

        for file in os.listdir(addon_path):
            if file.startswith('instance-settings-') and file.endswith('.xml'):
                file_path = os.path.join(addon_path, file)
                with open(file_path) as f:
                    data = f.read()
                # ensure no duplication in other instances
                if 'id="m3uPath">{}</setting>'.format(m3uPath) in data or 'id="epgUrl">{}</setting>'.format(epgUrl) in data:
                    xbmcvfs.delete(os.path.join(addon_path, file_path))
                else:
                    safe_copy(file_path, file_path+'.bu', del_src=True)
        pDialog.update(25)
        kodi_rpc('Addons.SetAddonEnabled', {
            'addonid': ADDON_ID, 'enabled': True})
        # wait for migration to occur
        while not os.path.exists(os.path.join(addon_path, 'instance-settings-1.xml')):
            monitor.waitForAbort(1)
        kodi_rpc('Addons.SetAddonEnabled', {
            'addonid': ADDON_ID, 'enabled': False})
        monitor.waitForAbort(1)

        safe_copy(os.path.join(addon_path, 'instance-settings-1.xml'),
                  instance_filepath, del_src=True)
        pDialog.update(35)
        with open(instance_filepath, 'r') as f:
            data = f.read()
        with open(instance_filepath, 'w') as f:
            f.write(data.replace('Migrated Add-on Config', ADDON_NAME))
        pDialog.update(50)
        for file in os.listdir(addon_path):
            if file.endswith('.bu'):
                safe_copy(os.path.join(addon_path, file), os.path.join(
                    addon_path, file[:-3]), del_src=True)
        kodi_rpc('Addons.SetAddonEnabled', {
            'addonid': ADDON_ID, 'enabled': True})
        pDialog.update(70)
    else:
        kodi_rpc('Addons.SetAddonEnabled', {
            'addonid': ADDON_ID, 'enabled': True})
        pDialog.update(70)

    set_kodi_setting('epg.futuredaystodisplay', 7)
    #  set_kodi_setting('epg.ignoredbforclient', True)
    set_kodi_setting('pvrmanager.syncchannelgroups', True)
    set_kodi_setting('pvrmanager.preselectplayingchannel', True)
    set_kodi_setting('pvrmanager.backendchannelorder', True)
    set_kodi_setting('pvrmanager.usebackendchannelnumbers', True)
    pDialog.update(100)
    pDialog.close()
    Script.notify("IPTV setup", "Epg and playlist updated")

    return True
>>>>>>> 0838c8b307651a6527aaaea4e75dfaa3db8f886a
