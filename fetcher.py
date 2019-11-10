import urllib.request
import re
import json
import os.path
import os
from time import time, sleep
from http.server import HTTPServer, BaseHTTPRequestHandler
from websocket_server import WebsocketServer
from base64 import b64decode
from urllib.parse import unquote as urlunq
from html import unescape as htmlunesc
import tempfile
from io import BytesIO
from zipfile import ZipFile
import sqlite3
import hashlib
import _thread
mdb_conn = sqlite3.connect("m.db", check_same_thread=False)
mdb = mdb_conn.cursor()
try:
    mdb.execute("""
    CREATE TABLE item (
    item_name TEXT,
    model_num INTEGER,
    pack_sha384 BLOB,
    updated_on INTEGER,
    UNIQUE(item_name,model_num,pack_sha384));""")
    mdb_conn.commit()
except sqlite3.OperationalError:
    pass
cachetime = (7*24*60*60)
cachedir = os.getcwd()+os.path.sep+'cache'
cwd = os.getcwd()+os.path.sep

def read_url(url, cache=True, noexpire=False):
    global cachetime
    if cache:
        cfile = cachedir+os.path.sep+re.sub(r'\W', '_', url)
        try:
            if os.path.getmtime(cfile)+cachetime > time():
                with open(cfile, 'rb') as file:
                    # print('read file')
                    page = file.read()
                    if noexpire:
                        os.utime(cfile, None)
                    return(page)
            else:
                os.remove(cfile)
                raise FileNotFoundError
        except FileNotFoundError:
            with open(cfile, 'wb') as file:
                print(f'fetching {url}')
                page = urllib.request.urlopen(url).read()
                # print('write file')
                file.write(page)
                return(page)
            pass
    else:
        print(f'fetching {url}')
        return(urllib.request.urlopen(url).read())


class McAssetManager(object):
    global cachetime
    """docstring for McAssetManager"""
    def __init__(self):
        super(McAssetManager, self).__init__()
        self._next_datacheck = 0
        self.versiondata = self.vdata()
        
    def vdata(self):
        global cachetime
        global cachedir
        if self._next_datacheck > time():
            return(self.versiondata)
        else:
            # cache clearing mechanism to free up disk space
            for filename in os.listdir(cachedir):
                if time() > os.path.getmtime(cachedir+os.path.sep+filename)+cachetime:
                    os.remove(cachedir+os.path.sep+filename)

            # get branches(gameversions) for mincraft-assets repository by InventivetalentDev
            branches = {b['name']:b for b in json.loads(read_url("https://api.github.com/repos/InventivetalentDev/minecraft-assets/branches?per_page=99999", False).decode())}
            # filter releases matching the game.major.minor versioning schema
            releases = list(filter(re.compile(r'^\d+\.\d+(\.\d+)?$').match, list(branches)))
            # filter versions to most recent major versions
            majorrel = dict({re.compile(r'^\d+\.\d+').match(r)[0]: r for r in releases})
            # filter releases where there should be custommodeldata; don't match known older releases
            validrel = {mj:mn for mj,mn in majorrel.items() if mj not in list(filter(re.compile(r'^1\.(\d|1[0-2])$').match, majorrel))}
            # get a list of all item models and where we can fetch their data
            ret = {}
            for mj,mn in validrel.items():
                sha = branches[mn]['commit']['sha'] # main dir
                for x in ['assets','minecraft','models','item']: # follow these directories
                    data = json.loads(read_url(f"https://api.github.com/repos/InventivetalentDev/minecraft-assets/git/trees/{sha}", True, True).decode())
                    for i in data['tree']:
                        if i['path'] == x: # find the next directory; continue.
                            sha = i['sha']
                # sha variable now points at assets/minecraft/models/item
                data = json.loads(read_url(f"https://api.github.com/repos/InventivetalentDev/minecraft-assets/git/trees/{sha}", True, True).decode())
                # return the data for this version; reduce to filename and sha 
                ret[mj] = {i['path'].split('.')[0]: i['sha'] for i in data['tree']}
            self._next_datacheck = time()+cachetime # set the next check time and return data
            return(ret)


class S(BaseHTTPRequestHandler):
    def _set_headers(self, contype="text/html", resp=200):
        self.send_response(resp)
        self.send_header("Content-type", contype)
        self.end_headers()

    def _msgdump(self, message="OK", resp=200):
        self._set_headers("text/html", resp)
        self.wfile.write(f"<html><body><h1>{resp}: {message}</h1></body></html>".encode())

    def _jdump(self, data, resp=200):
        self._set_headers("application/json", resp)
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        global mcasset
        stuff = self.path.split('?')
        if len(stuff) < 2:
            stuff.append('')
        path = stuff[0].strip('/').split('/')
        query = [q.split('=', 1) for q in stuff[1].split('&')]
        if path[0] == '' or path[0] == 'index.html':
            self._set_headers()
            # self.wfile.write(self._html("hi!: "+"\n"+json.dumps(mcasset.vdata())))
            # self.wfile.write(self._html("this is the main page!"))
            self.wfile.write(open(cwd+'index.html', 'r').read().encode())
        elif len(path) == 1 and path[0] == 'api': # list valid api options
            self._jdump(['item-models', 'pack', 'registered'])
        elif len(path) == 2 and path[0] == 'api' and path[1] == 'pack': # join multiple resource packs together, with overrides merge
            try:
                cfilename = f'pack{hash(json.dumps(query))}.zip'
                cfile = cachedir+os.path.sep+cfilename
                if not (os.path.isfile(cfile) and os.path.getmtime(cfile)+cachetime > time()): # check if the work has been done already
                    print('merging packs')
                    now = time()
                    with tempfile.TemporaryDirectory() as tmp:
                        os.chdir(tmp) # work in a temporary directory
                        for k, v in query:
                            if k == 'url':
                                v = urlunq(v)
                                # print(k, v)
                                opener = BytesIO(read_url(v))
                                ziphash = hashlib.sha384()
                                ziphash.update(opener.getvalue())
                                ziphash = ziphash.digest()
                                zipfile = ZipFile(opener)
                                for member in zipfile.namelist():
                                    result = re.search(r'assets\/minecraft\/models\/item\/(.+)\.json$', member)
                                    if result:
                                        nwfl = json.loads(zipfile.read(member)) # read file from zip
                                        if 'overrides' in nwfl and len(nwfl['overrides']) > 0: # if overrides
                                            for x in nwfl['overrides']: # add model numbers to database
                                                if 'predicate' in x and 'custom_model_data' in x['predicate']:
                                                    m = x['predicate']['custom_model_data']
                                                    # print(f"]== override:\nitem:{result[1]}\nmodelnum:{m}\npackhash:{ziphash}\nurl:{v}\ntime:{now}")
                                                    mdb.execute("INSERT or REPLACE INTO item VALUES (?, ?, ?, ?)", (result[1], m, ziphash, int(now)))
                                                    send_obj({"gl_itemmodel_update":[result[1], m, ziphash.hex(), int(now)]})
                                            if os.path.isfile(member): # do override merging
                                                exst = json.load(open(member)) # read existing file
                                                if 'overrides' not in exst: # if no overrides, create
                                                    exst['overrides'] = []
                                                exst['overrides'].extend(nwfl['overrides']) # merge overrides
                                                open(member, 'w').write(json.dumps(orig, indent=4, sort_keys=True)) # dump json to file
                                    if not os.path.isfile(member): # if no file, extract it
                                        zipfile.extract(member)
                                mdb_conn.commit()
                        with ZipFile(cfile, 'w') as zipObj: # zip up temp directory, to cache
                            for folderName, subfolders, filenames in os.walk('.'):
                                for filename in filenames:
                                    filePath = os.path.join(folderName, filename)
                                    zipObj.write(filePath)
                with open(cfile, 'rb') as file: # offer zip file download, from cache
                    self.send_response(200)
                    self.send_header("Content-type", "application/zip")
                    self.send_header("Content-Disposition", f'attachment; filename="{cfilename}"')
                    self.end_headers()
                    self.wfile.write(file.read())
            except ValueError:
                self._jdump({'FORMAT':'/api/pack/?url=<resourcepackurl1>&url=<resourcepackurl2>&url=<resourcepackurl3>','USE':'combine your super special resource packs, with predicate merging'})
                pass
        elif len(path) == 2 and path[0] == 'api' and path[1] == 'registered':
            if query[0][0] == '': # if no query
                # serve most recent additions to database
                self._jdump([{'item_name':i,'model_num':n,'pack_sha384':s.hex(),'updated_on':u} for i,n,s,u in mdb.execute("SELECT * FROM item ORDER BY updated_on DESC LIMIT 64")])
                # # serve entire database
                # self._jdump([{'item_name':i,'model_num':n,'pack_sha384':s.hex(),'updated_on':u} for i,n,s,u in mdb.execute("select * from item")])
            else:
                # TODO serve specific item/modelnum/packhash/etc from database
                pass
        elif len(path) >= 2 and path[0] == 'api' and path[1] == 'item-models':
            if len(path) == 2: # if no version number specified, list the versions avail
                vhist = read_url(f"https://minecraft.gamepedia.com/Java_Edition_version_history").decode()
                self._jdump({v:htmlunesc(re.search(r'mw-headline[^>]+>'+v+r'(?:[^>]+>){24}(?:[^\"]+\"){2} title=\"([^\"]+)\"', vhist)[1]) for v in mcasset.vdata().keys()})
            elif len(path) >= 3 and path[2] in mcasset.vdata(): # if version valid, send list of item models
                if len(path) >= 4:
                    if path[3] in mcasset.vdata()[path[2]]:
                        self._set_headers("application/json")
                        self.wfile.write(b64decode(json.loads(read_url(f"https://api.github.com/repos/InventivetalentDev/minecraft-assets/git/blobs/{mcasset.vdata()[path[2]][path[3]]}", True, True).decode())['content']))
                else:
                    self._jdump(mcasset.vdata()[path[2]])
        else:
            self._msgdump("Not Found", 404)
    def do_HEAD(self):
        self._set_headers()

    def do_POST(self):
        # Doesn't do anything with posted data
        self._msgdump("POST!")
def send_obj(obj, client=False):
    if client==False:
        ws_server.send_message_to_all(json.dumps(obj))
    else:
        ws_server.send_message(client, json.dumps(obj))

# Called for every client connecting (after handshake)
def new_client(client, server):
    print("New client connected and was given id %d" % client['id'])
    for i,n,s,u in reversed(list(mdb.execute("SELECT * FROM item ORDER BY updated_on DESC LIMIT 16"))):
        send_obj({"gl_itemmodel_update":[i,n,s.hex(),u]}, client) 

# Called for every client disconnecting
def client_left(client, server):
    print("Client(%d) disconnected" % client['id'])
# Called when a client sends a message
def message_received(client, server, message):
    for k, v in json.loads(message).items():
        print(k, v)
    # print("Client(%d) said: %s" % (client['id'], message))
    # server.send_message_to_all("Client(%d) said: %s" % (client['id'], message))
    # server.send_message(client, "")

if __name__ == "__main__":
    print("Loading MCAssetManager")
    mcasset = McAssetManager()
    print("Loading WebsocketServer")
    ws_server = WebsocketServer(1388, host='')
    ws_server.set_fn_new_client(new_client)
    ws_server.set_fn_client_left(client_left)
    ws_server.set_fn_message_received(message_received)
    _thread.start_new_thread(ws_server.run_forever, ())
    print(f"Loading HTTPServer")
    HTTPServer(('', 80), S).serve_forever()