import urllib.request
import re
import json
import os.path
import os
from time import time
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from base64 import b64decode
cachetime = (7*24*60*60)

def read_url(url, cache=True):
    global cachetime
    if url.startswith('http'):
        if cache:
            cfile = "cache"+os.path.sep+re.sub(r'\W', '_', url)
            try:
                if os.path.getmtime(cfile)+cachetime > time():
                    with open(cfile, 'r') as file:
                        # print('read file')
                        page = file.read()
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

            branches = {b['name']:b for b in json.loads(read_url("https://api.github.com/repos/InventivetalentDev/minecraft-assets/branches?per_page=99999", False))}
            # releases matching the game.major.minor versioning schema
            releases = list(filter(re.compile(r'^\d+\.\d+(\.\d+)?$').match, list(branches)))
            # removing .minor suffix and noting down most recent ver
            majorrel = dict({re.compile(r'^\d+\.\d+').match(r)[0]: r for r in releases})
            # get releases where there should be custommodeldata (don't match known older releases)
            validrel = {mj:mn for mj,mn in majorrel.items() if mj not in list(filter(re.compile(r'^1\.(\d|1[0-2])$').match, majorrel))}
            # get a list of all item models and where we can fetch their data
            ret = {}
            for mj,mn in validrel.items():
                sha = branches[mn]['commit']['sha']
                # follow these directories
                for x in ['assets','minecraft','models','item']:
                    # print(x)
                    data = json.loads(read_url(f"https://api.github.com/repos/InventivetalentDev/minecraft-assets/git/trees/{sha}"))
                    for i in data['tree']:
                        if i['path'] == x:
                            sha = i['sha']
                # sha variable now points at assets/minecraft/models/item for the specified version
                data = json.loads(read_url(f"https://api.github.com/repos/InventivetalentDev/minecraft-assets/git/trees/{sha}"))
                ret[mj] = {i['path'].split('.')[0]: i['sha'] for i in data['tree']}
                # # list all the item models
                # print([i['path'] for i in data['tree'] if i['type']=='blob'])
            self._next_datacheck = time()+cachetime
            return(ret)


class S(BaseHTTPRequestHandler):
    def _set_headers(self, contype="text/html", resp=200):
        self.send_response(resp)
        self.send_header("Content-type", contype)
        self.end_headers()

    def _html(self, message):
        """This just generates an HTML document that includes `message`
        in the body. Override, or re-write this do do more interesting stuff.

        """
        content = f"<html><body><h1>{message}</h1></body></html>"
        return content.encode("utf8")  # NOTE: must return a bytes object!

    def do_GET(self):
        global mcasset
        path = self.path.strip('/').split('/')
        if path[0] == 'api':
            self._set_headers("application/json")
        if path[0] == '' or path[0] == 'index.html':
            self._set_headers()
            # self.wfile.write(self._html("hi!: "+"\n"+json.dumps(mcasset.vdata(), indent=4, sort_keys=True)))
            # self.wfile.write(self._html("this is the main page!"))
            self.wfile.write(read_url('index.html'))
        elif len(path) == 1 and path[0] == 'api':
            self.wfile.write(json.dumps(['item-models'], indent=4, sort_keys=True).encode())
        elif len(path) >= 2 and path[0] == 'api' and path[1] == 'item-models':
            if len(path) == 2:
                self.wfile.write(json.dumps(list(mcasset.vdata().keys()), indent=4, sort_keys=True).encode())
            elif len(path) >= 3 and path[2] in mcasset.vdata():
                if len(path) >= 4:
                    if path[3] in mcasset.vdata()[path[2]]:
                        # self.wfile.write(json.dumps(mcasset.vdata()[path[2]][path[3]], indent=4, sort_keys=True).encode())
                        self.wfile.write(b64decode(json.loads(read_url(f"https://api.github.com/repos/InventivetalentDev/minecraft-assets/git/blobs/{mcasset.vdata()[path[2]][path[3]]}"))['content']))
                        # self.wfile.write()   
                else:
                    self.wfile.write(json.dumps(mcasset.vdata()[path[2]], indent=4, sort_keys=True).encode())
        else:
            self._set_headers("text/html", 404)
            self.wfile.write(self._html("404: Not Found"))
    def do_HEAD(self):
        self._set_headers()

    def do_POST(self):
        # Doesn't do anything with posted data
        self._set_headers()
        self.wfile.write(self._html("POST!"))


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
