#!/usr/bin/env python

import Tnet

session_id = raw_input('Session id: ')
storage = Tnet.Storage(session_id)
#folders = storage.list_folders()
#storage.store_file(Tnet.Folder("w00t",4069,[]), 'test.txt', "Hello world!\n")
