import hashlib, cookielib, random, re, urllib, urllib2

MAX_FILE_SIZE=15728640


def make_mime_boundary():
    'Generates a random text string to be used as a MIME message boundary'

    # Generate a 144-bit random string
    data = ''.join(map(chr, [random.randint(0,255) for _ in range(18)]))

    # Return base-64 encoded string (this will have length 144/6 == 24)
    return data.encode('base64').strip()


def urldecode(s):
    t = ''
    for ch in re.findall('%[0-9A-Fa-f]{2}|.', s):
        if ch[0] == '%':
            t += chr(int(ch[1:], 16))
        else:
            t += ch
    return t


def urlencode(s):
    t = ''
    for ch in s:
        if ch.isalnum():
            t += ch
        else:
            t += '%%%02X' % ord(ch)
    return t


def parse_file_listing(page, folder_id):
    'Parses a folder page and returns a list of files contained'

    files = []
    pattern = '<td><a href="[^">]+[?]action=download_file&file_id=([0-9]+)">' \
              '([^<]*)</a></td>\s*<td[^>]*>([a-z0-9]{32})</td>\s*'            \
              '<td>([0-9]+)(B|KB|MB)</td>\s*<td>([^>]*)</td>';
    for id, name, md5, size, unit, mtime in re.findall(pattern, page):

        # Figure out (approximate) size in bytes
        bytes = int(size)
        if unit == 'KB': bytes *= 2**10
        if unit == 'MB': bytes *= 2**20

        # TODO: parse mtime, which can be of the form "12:34"
        # FIXME: which time zone to use?
        files.append(File(name, int(id), folder_id, md5, bytes, 0))

    return files


def parse_folder_listing(page):
    # Split page up into lines
    lines = page.split('\n')

    # Search for line containing folder info
    lineFound = False
    for line in lines:
        if lineFound: break
        lineFound = line.find('<li class="openTreeFolderStatic" ') >= 0
    else:
        return None

    # Parse folder info
    root_folder = cur_folder = Folder('Index', 0)
    pattern = '<li[^>]+title="([^>"]+)"[^>]*><a href="[^">]+?map=([0-9]+)">|(</li>)'
    for name, id, end in re.findall(pattern, line):
        if not end:
            cur_folder = Folder(name, int(id), parent=cur_folder)
        else:
            cur_folder = cur_folder.parent
    assert root_folder == cur_folder
    return root_folder


class Folder:
    'Represents a T.net storage folder.'

    def __init__(self, name, id, children = [], parent = None):
        self.name       = name
        self.id         = id
        self.parent     = None
        self.children   = []
        if parent is not None:
            parent.add_child(self)
        for ch in children:
            self.add_child(ch)

    def add_child(self, child):
        if child not in self.children:
            if child.parent is not None:
                child.parent.remove_child(child)
            self.children.append(child)
            child.parent = self

    def remove_child(self, child):
        if child in self.children:
            self.children.remove(child)
            child.parent = None

    def is_ancestor_of(self, descendant):
        while descendant is not None:
            if descendant.id == self.id:
                return True
            descendant = descendant.parent
        return False

    def is_descendant_of(self, ancestor):
        # NOTE: assumes ancestor is not None
        return ancestor.is_ancestor_of(self)

    def find(self, folder_id):
        'Search for a folder with the given id in this subtree'

        if self.id == folder_id:
            return self
        for child in self.children:
            folder = child.find(folder_id)
            if folder is not None:
                return folder
        return None

    def __eq__(self, other):
        if other.__class__ != self.__class__:
            return False
        return (self.name, self.id) == (other.name, other.id)

    def __ne__(self, other):
        return not (self == other)

    def __str__(self):
        return '<Tnet.Folder "%s">' % self.name

    def __repr__(self):
        children = ','.join(map(repr, self.children))
        return 'Tnet.Folder("%s",%d,[%s])' % (self.name, self.id, children)

    def __len__(self):
        return len(self.children)

    def __iter__(self):
        return self.children.__iter__()

    def __getitem__(self, n):
        return self.children[n]


class File:
    'Represents a T.net storage file'

    def __init__(self, name, id, folder_id, md5, size, mtime):
        self.name       = name
        self.id         = id
        self.folder_id  = folder_id
        self.md5        = md5
        self.size       = size
        self.mtime      = mtime

    def contents(self):
        return (self.name, self.id, self.folder_id,
                self.md5, self.size, self.mtime)

    def __eq__(self, other):
        if other.__class__ != self.__class__:
            return False
        return self.contents() == other.contents()

    def __ne__(self, other):
        return not (self == other)

    def __str__(self):
        return '<Tnet.File "%s">' % self.name

    def __repr__(self):
        return 'Tnet.File("%s",%d,%d,"%s",%d,%d)' % ( self.name, self.id,
            self.folder_id, self.md5, self.size, self.mtime )


class Storage:
    'Represents the T.net private storage service'

    def __init__( self, session_id,
                  secure = False, domain = 'tweakers.net', port = 80,
                  base_path = '/my.tnet/storage' ):

        self.base_url = 'http://' + domain + base_path

        session_cookie = cookielib.Cookie(
            version             = 0,
            name                = 'TnetID',
            value               = session_id,
            port                = None,
            port_specified      = False,
            domain              = '.' + domain,
            domain_specified    = True,
            domain_initial_dot  = True,
            path                = base_path,
            path_specified      = True,
            secure              = secure,
            expires             = None,
            discard             = True,
            comment             = None,
            comment_url         = None,
            rest                = None,
            rfc2109             = False )

        self.cookiejar = cookielib.CookieJar()
        self.cookiejar.set_cookie(session_cookie)

        cookie_processor = urllib2.HTTPCookieProcessor(self.cookiejar)
        self.opener = urllib2.build_opener(cookie_processor)

    def list_folders(self):
        'Returns a dummy folder containing all available folders recursively.'

        # HTTP request to retrieve folder listing
        page = self.opener.open(self.base_url).read()

        return parse_folder_listing(page)


    def list_files(self, folder):
        'Returns a list of files in the given folder'

        assert folder.id > 0

        request = self.opener.open(self.base_url + '?map=' + str(folder.id))
        return parse_file_listing(request.read(), folder.id)

    def retrieve_file(self, file):
        'Returns the contents of the given file.'

        assert file.id > 0

        # HTTP request to retrieve file listing
        query   = '?action=download_file&file_id=' + str(file.id)
        request = self.opener.open(self.base_url + query)
        data    = request.read()

        # Verify checksum
        md5 = hashlib.md5()
        md5.update(data)
        md5 = md5.hexdigest()
        if md5 <> file.md5:
            return None
        return data

    def store_file(self, folder, filename, contents):
        'Creates a new file with the specified name and contents'

        assert folder.id > 0
        assert len(contents) < MAX_FILE_SIZE

        url = self.base_url + '?action=upload&map=' + str(folder.id)
        boundary = make_mime_boundary()
        data = '--' + boundary + '\r\n'                                 \
               'Content-Disposition: form-data; name="bestand[1]";'     \
               ' filename="' + filename + '"\r\n\r\n' +                 \
               contents + '\r\n--' + boundary + '--\r\n'
        headers = {
            'Content-Type': 'multipart/form-data; boundary=' + boundary }
        page = self.opener.open(urllib2.Request(url, data, headers)).read()
        return page.find('Alle bestanden zijn successvol verwerkt.') >= 0

    def delete_file(self, file):
        'Deletes the specified file'

        assert file.id > 0
        assert file.folder_id > 0

        data = urllib.urlencode({
            'map_id':   file.folder_id,
            'files':    urlencode('a:1:{i:' + str(file.id) + ';s:1:"1";}') })
        url = self.base_url + '?action=massdelete2'
        page = self.opener.open(url, data).read()
        return file not in parse_file_listing(page, file.folder_id)

    def delete_folder(self, src_folder, dst_folder = None):
        '''Deletes the source folder and moves its contents to the destination
           folder, if given. The destination folder may not be a descendant of
           the source folder.'''

        assert src_folder.id > 0
        data_parts = {'delete': '1'}
        if dst_folder is not None:
            assert dst_folder.id > 0
            assert not src_folder.is_ancestor_of(dst_folder)
            data_parts['deleteoption'] = 'move'
            data_parts['move_to_map_id'] = dst_folder.id
        else:
            data_parts['deleteoption'] = 'delete'
        url = self.base_url + '?action=editmap2&map_id=' + str(src_folder.id)
        data = urllib.urlencode(data_parts)
        page = self.opener.open(url, data).read()
        return page.find('De map is verwijderd.') >= 0

    def rename_folder(self, folder, new_name):
        "Changes the given folder's name"

        assert folder.id > 0
        url = self.base_url + '?action=editmap2&map_id=' + str(folder.id)
        data = urllib.urlencode({'mapnaam': new_name})
        page = self.opener.open(url, data).read()
        return page.find('De map is aangepast.') >= 0

    def move_file(self, file, folder):
        'Moves the given file to the specified folder'

        assert folder.id > 0
        url = self.base_url + '?action=massverplaatsen'
        data = urllib.urlencode({
            'map_id':   folder.id,
            'files':    urlencode('a:1:{i:' + str(file.id) + ';s:1:"1";}') })
        page = self.opener.open(url, data).read()
        return True

    def move_folder(self, src_folder, dst_folder):
        '''Moves the given source folder to a new destination. This destination
           may not be a descendant of the source folder.'''

        assert not src_folder.is_ancestor_of(dst_folder)
        # This seems to be unimplemented on the server as of 17 March 2009
        #url = self.base_url + '?action=editmap2&map_id=' + str(src_folder.id)
        #data = urllib.urlencode([('new_parent_id', dst_folder.id)])
        #page = self.opener.open(url, data).read()
        #return page.find('De map is aangepast.') >= 0
        return False

    def rename_folder(self, folder, new_name):
        "Changes the given folder's name"

        assert folder.id > 0
        url = self.base_url + '?action=editmap2&map_id=' + str(folder.id)
        data = urllib.urlencode([('mapnaam', new_name)])
        page = self.opener.open(url, data).read()
        return page.find('De map is aangepast.') >= 0

    def create_folder(self, parent_folder, new_name):
        "Creates a new folder with the given name"

        url = self.base_url + '?action=addmap'
        data = urllib.urlencode([ ('mapnaam', new_name),
                                  ('map_id',  parent_folder.id) ])
        page = self.opener.open(url, data).read()
        return page.find('De map is aangemaakt.') >= 0
