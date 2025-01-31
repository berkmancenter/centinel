import pycurl
import re
from StringIO import StringIO


class ICHTTPConnection:

    def __init__(self, host='127.0.0.1', port=None, timeout=10):
        self.headers = {}
        self.body = None
        self.reason = None
        self.status = 0
        self.host = host
        self.port = port
        self.timeout = timeout
        # Follows the HAR timing spec
        self.timings = {
            "send": 0,
            "wait": 0,
            "receive": 0,
            "ssl": -1
        }


    def header_function(self, header_line):
        # HTTP standard specifies that headers are encoded in iso-8859-1.
        # On Python 2, decoding step can be skipped.
        # On Python 3, decoding step is required.
        # header_line = header_line.decode('iso-8859-1')

        # Header lines include the first status line (HTTP/1.x ...).
        # We are going to ignore all lines that don't have a colon in them.
        # This will botch headers that are split on multiple lines...
        if self.reason is None:
            reason = re.match('^HTTP/\d\.\d \d{3} (\w+)', header_line)
            if reason is not None:
                self.reason = reason.group(1)
        if ':' not in header_line:
            return

        # Break the header line into header name and value.
        name, value = header_line.split(':', 1)

        # Remove whitespace that may be present.
        # Header lines include the trailing newline, and there may be whitespace
        # around the colon.
        name = name.strip()
        value = value.strip()

        # Header names are case insensitive.
        # Lowercase name here.

        # Now we can actually record the header name and value.
        self.headers[name] = value

    def request(self, path="/", header=None, ssl=False, timeout=None):

        if timeout is None:
            timeout = self.timeout

        buf = StringIO()
        c = pycurl.Curl()

        if header:
            slist = []
            for key, value in header.iteritems():
                slist.append(key+": "+value)
            c.setopt(pycurl.HTTPHEADER, slist)

        c.setopt(pycurl.HEADERFUNCTION, self.header_function)
        c.setopt(pycurl.FOLLOWLOCATION, True)
        c.setopt(pycurl.WRITEDATA, buf)
        c.setopt(pycurl.TIMEOUT, timeout)
        c.setopt(pycurl.ENCODING, 'identity')
        c.setopt(pycurl.NOSIGNAL, 1)

        if ssl:
            if self.port is None:
                self.port = 443
            c.setopt(pycurl.URL, "https://"+self.host+":"+str(self.port)+path)
            c.setopt(pycurl.SSL_VERIFYPEER, 1)
            c.setopt(pycurl.SSL_VERIFYHOST, 2)
        else:
            if self.port is None:
                self.port = 80
            c.setopt(pycurl.URL,"http://"+self.host + ":" + str(self.port) + path)

        c.perform()

        self.status = c.getinfo(pycurl.RESPONSE_CODE)

        # It's not exactly clear from the docs
        # (https://curl.haxx.se/libcurl/c/curl_easy_getinfo.html#TIMES) how to
        # map those times to HAR timings, but here's my best guess.
        ROUND_TO = 3
        self.timings['dns'] = round(c.getinfo(pycurl.NAMELOOKUP_TIME) * 1000, ROUND_TO)
        self.timings['wait'] = round((c.getinfo(pycurl.STARTTRANSFER_TIME) -
                c.getinfo(pycurl.PRETRANSFER_TIME)) * 1000, ROUND_TO)
        self.timings['receive'] = round((c.getinfo(pycurl.TOTAL_TIME) -
                c.getinfo(pycurl.STARTTRANSFER_TIME)) * 1000, ROUND_TO)
        if ssl:
            self.timings['ssl'] = round((c.getinfo(pycurl.APPCONNECT_TIME) -
                    c.getinfo(pycurl.CONNECT_TIME)) * 1000, ROUND_TO)
            self.timings['connect'] = round((c.getinfo(pycurl.APPCONNECT_TIME) -
                        c.getinfo(pycurl.NAMELOOKUP_TIME)) * 1000, ROUND_TO)
            self.timings['send'] = round((c.getinfo(pycurl.PRETRANSFER_TIME) -
                        c.getinfo(pycurl.APPCONNECT_TIME)) * 1000, ROUND_TO)
        else:
            self.timings['connect'] = round((c.getinfo(pycurl.CONNECT_TIME) -
                        c.getinfo(pycurl.NAMELOOKUP_TIME)) * 1000, ROUND_TO)
            self.timings['send'] = round((c.getinfo(pycurl.PRETRANSFER_TIME) -
                        c.getinfo(pycurl.CONNECT_TIME)) * 1000, ROUND_TO)

        c.close()

        encoding = None
        if 'content-type' in self.headers:
            content_type = self.headers['content-type'].lower()
            match = re.search('charset=(\S+)', content_type)
            if match:
                encoding = match.group(1)
        if encoding is None:
            # Default encoding for HTML is iso-8859-1.
            # Other content types may have different default encoding,
            # or in case of binary data, may have no encoding at all.
            encoding = 'iso-8859-1'

        self.body = buf.getvalue().decode(encoding)
