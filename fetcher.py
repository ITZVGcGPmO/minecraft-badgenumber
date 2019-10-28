import urllib.request
import re
import json
import os.path
import os
from time import time
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from base64 import b64decode
from urllib.parse import unquote as urlunq
from html import unescape as htmlunesc
cachetime = (7*24*60*60)

def read_url(url, cache=True, noexpire=False):
    global cachetime
    if url.startswith('http'):
        if cache:
            cfile = "cache"+os.path.sep+re.sub(r'\W', '_', url)
            try:
                if os.path.getmtime(cfile)+cachetime > time():
                    with open(cfile, 'r') as file:
                        # print('read file')
                        page = file.read()
                        if noexpire:
                            os.utime(cfile, None)
                        return(page)
                else:
                    os.remove(cfile)
                    raise FileNotFoundError
            except FileNotFoundError:
                with open(cfile, 'w') as file:
                    print(f'fetching {url}')
                    page = urllib.request.urlopen(url).read().decode()
                    # print('write file')
                    file.write(page)
                    return(page)
                pass
        else:
            print(f'fetching {url}')
            return(urllib.request.urlopen(url).read().decode())
    else:
        return(open(url, 'r').read().encode())


class McAssetManager(object):
    global cachetime
    """docstring for McAssetManager"""
    def __init__(self):
        super(McAssetManager, self).__init__()
        self._next_datacheck = 0
        self.versiondata = self.vdata()
        
    def vdata(self):
        global cachetime
        if self._next_datacheck > time():
            return(self.versiondata)
        else:
            # cache clearing mechanism to free up disk space
            for filename in os.listdir('cache'):
                if time() > os.path.getmtime('cache'+os.path.sep+filename)+cachetime:
                    os.remove('cache'+os.path.sep+filename)

            # get branches(gameversions) for mincraft-assets repository by InventivetalentDev
            branches = {b['name']:b for b in json.loads(read_url("https://api.github.com/repos/InventivetalentDev/minecraft-assets/branches?per_page=99999", False))}
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
                    data = json.loads(read_url(f"https://api.github.com/repos/InventivetalentDev/minecraft-assets/git/trees/{sha}", True, True))
                    for i in data['tree']:
                        if i['path'] == x: # find the next directory; continue.
                            sha = i['sha']
                # sha variable now points at assets/minecraft/models/item
                data = json.loads(read_url(f"https://api.github.com/repos/InventivetalentDev/minecraft-assets/git/trees/{sha}", True, True))
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
            self.wfile.write(read_url('index.html'))
        elif len(path) == 1 and path[0] == 'api':
            self._jdump(['item-models', 'pack'])
        elif len(path) == 2 and path[0] == 'api' and path[1] == 'pack':
            print('yay!')
            ids = set()
            for k, v in query:
                if k == 'url':
                    print(k, v)
                    v = urlunq(v)
                    # do url stuff
                if k == 'id':
                    v = [int(y) for y in v.split('-')] # generate list of integers split by '-'
                    if len(v) < 2: # if only 1 integer, use that as both start and end
                        v.append(v[0])
                    ids.update(range(v[0], v[1]+1)) # add range from start to end to our id set
            print(ids)
            print(query)
            self._jdump(['yay'])
        elif len(path) >= 2 and path[0] == 'api' and path[1] == 'item-models':
            if len(path) == 2: # if no version number specified, list the versions avail
                vhist = read_url(f"https://minecraft.gamepedia.com/Java_Edition_version_history")
                self._jdump({v:htmlunesc(re.search(r'mw-headline[^>]+>'+v+r'(?:[^>]+>){24}(?:[^\"]+\"){2} title=\"([^\"]+)\"', vhist)[1]) for v in mcasset.vdata().keys()})
            elif len(path) >= 3 and path[2] in mcasset.vdata(): # if version valid, send list of item models
                if len(path) >= 4:
                    if path[3] in mcasset.vdata()[path[2]]:
                        # self._jdump(mcasset.vdata()[path[2]][path[3]])
                        self.wfile.write(b64decode(json.loads(read_url(f"https://api.github.com/repos/InventivetalentDev/minecraft-assets/git/blobs/{mcasset.vdata()[path[2]][path[3]]}", True, True))['content']))
                        # self.wfile.write()   
                else:
                    self._jdump(mcasset.vdata()[path[2]])
        else:
            self._msgdump("Not Found", 404)
    def do_HEAD(self):
        self._set_headers()

    def do_POST(self):
        # Doesn't do anything with posted data
        self._msgdump("POST!")


def run(server_class=HTTPServer, handler_class=S, addr="localhost", port=8000):
    server_address = (addr, port)
    httpd = server_class(server_address, handler_class)

    print(f"Starting httpd server on {addr}:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a simple HTTP server")
    parser.add_argument(
        "-l",
        "--listen",
        default="localhost",
        help="Specify the IP address on which the server listens",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=8000,
        help="Specify the port on which the server listens",
    )
    args = parser.parse_args()
    print("Loading MCAssetManager")
    mcasset = McAssetManager()
    run(addr=args.listen, port=args.port)
