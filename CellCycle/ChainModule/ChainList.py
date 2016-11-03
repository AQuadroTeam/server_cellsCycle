#! /usr/bin/env python


class ChainList:

    def __init__(self):
        self.dictionary = dict()

    def add_node(self, target_node, target_master, target_slave):
        list_key = ListKey(target_node.id)
        list_value = ListValue(target_node)
        list_value.add_master(target_master)
        list_value.add_slave(target_slave)
        self.dictionary[list_key.key] = list_value

    def remove_node(self, target_id):
        try:
            del(self.dictionary[target_id])
        except KeyError:
            raise KeyError

    # Search for a memory key in list, returns None if key_to_find is not part of the dictionary
    def find_memory_key(self, key_to_find):
        for k, v in self.dictionary.iteritems():
            if v.master.min_key <= key_to_find <= v.master.max_key or\
               v.slave.min_key <= key_to_find <= v.slave.max_key:
                return v
        return None

    # Returns a value with a key as parameter
    def get_value(self, key):
        try:
            return self.dictionary[key]
        except KeyError:
            raise KeyError

    # Is this id in list
    def is_in_list(self, key):
        return key in self.dictionary


class ListKey:

    def __init__(self, target_key):
        self.key = target_key


class ListValue:

    def __init__(self, target):
        self.target = target
        self.master = None
        self.slave = None

    def add_master(self, target):
        self.master = target

    def add_slave(self, target):
        self.slave = target
