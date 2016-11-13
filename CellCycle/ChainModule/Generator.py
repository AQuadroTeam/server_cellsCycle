#! /usr/bin/env python

from ListThread import Node, ListThread
from DeadReader import DeadReader
from DeadWriter import DeadWriter

MYSELF = 'myself'
MASTER = 'master'
SLAVE = 'slave'
MASTER_OF_MASTER = 'master_of_master'
SLAVE_OF_SLAVE = 'slave_of_slave'

ID = 'id'
IP = 'ip'
MIN_KEY = 'min_key'
MAX_KEY = 'max_key'

# unused
# def get_args():
#     parser = ArgumentParser(description='Process Cells Cycle')
#     parser.add_argument('myself', type=list, help='the node we are talking about')
#     parser.add_argument('master', type=list, help='the node\'s master')
#     parser.add_argument('slave', type=list, help='the node\'s slave')
#     parser.add_argument('master_of_master', type=list, help='the node\'s master of master')
#     parser.add_argument('slave_of_slave', type=list, help='the node\'s slave of slave')

#     return parser.parse_args()
LOCAL_HOST = '127.0.0.1'


class Generator:
    def __init__(self, logger, settings, json_arg):
        self.logger = logger
        self.settings = settings
        self.args = json_arg
        self._writer = None
        self._reader = None

    def _get_node_from_data(self, data):
        return Node(data[ID], data[IP], self.settings.getIntPort(),
                    self.settings.getExtPort(), min_key=data[MIN_KEY], max_key=data[MAX_KEY],
                    memory_port=self.settings.getMemoryObjectPort())

    def get_reader(self):
        return self._reader

    def get_writer(self):
        return self._writer

    def start_reader_writer(self):
        self._reader.start()
        self._writer.start()
        self._reader.join()

    def create_process_environment(self):
        myself = self.args[MYSELF]
        myself = self._get_node_from_data(myself)
        master = self.args[MASTER]
        master = self._get_node_from_data(master)
        slave = self.args[SLAVE]
        slave = self._get_node_from_data(slave)
        master_of_master = self.args[MASTER_OF_MASTER]
        master_of_master = self._get_node_from_data(master_of_master)
        slave_of_slave = self.args[SLAVE_OF_SLAVE]
        slave_of_slave = self._get_node_from_data(slave_of_slave)

        thread_reader_name = "Reader-{}".format(myself.id)
        thread_writer_name = "Writer-{}".format(myself.id)
        writer = DeadWriter(myself, master, slave, slave_of_slave, master_of_master, self.logger, self.settings,
                            thread_writer_name)
        reader = DeadReader(myself, master, slave, slave_of_slave, master_of_master, self.logger, self.settings,
                            thread_reader_name, writer)

        self._reader = reader
        self._writer = writer


class Parameter:    # unused

    def __init__(self, myself, master, slave, master_of_master, slave_of_slave):
        self.myself = myself
        self.slave = slave
        self.slave_of_slave = slave_of_slave
        self.master = master
        self.master_of_master = master_of_master


def scale_down_thread(a, l):
    from CellCycle.ChainModule.ListCommunication import InternalChannel
    internal_channel_server = InternalChannel(addr='127.0.0.1', port=a.memory_port, logger=l)
    internal_channel_server.generate_internal_channel_server_side()
    internal_channel_server.wait_int_message(dont_wait=False)
    internal_channel_server.reply_to_int_message("OK")

    # myself = Generator._get_node_from_data(a[MYSELF])
    internal_channel = InternalChannel(addr='127.0.0.1', port=a.int_port, logger=l)
    internal_channel.generate_internal_channel_client_side()

    # if myself.int_port == 1:

    ListThread.notify_restored(internal_channel)
    # else:
    #     while True:
    #         sleep(5)


def scale_up_thread(a, l):
    from CellCycle.ChainModule.ListCommunication import InternalChannel

    # myself = Generator._get_node_from_data(a[MYSELF])
    internal_channel = InternalChannel(addr='127.0.0.1', port=a.int_port, logger=l)
    internal_channel.generate_internal_channel_client_side()

    # while True:
    ListThread.notify_scale_up(internal_channel)
    #     sleep(5)

    # else:
    #     while True:
    #         sleep(5)


def gen(l, s, a):
    generator = Generator(logger=l, settings=s, json_arg=a)
    writer = generator.create_process_environment()
    writer.join()


def create_single_process(l, s, a):
    new_process = Process(name="Process-"+str(n), target=gen, args=(l, s, a, ))
    new_process.start()


if __name__ == "__main__":
    from firstLaunchAWS import create_instances_parameters
    from start import loadSettings
    from start import loadLogger

    params = create_instances_parameters()
    currentProfile = {"profile_name": "alessandro_fazio", "key_pair": "AWSCellCycle", "branch": "ListUtilities"}
    settings_to_launch = loadSettings(currentProfile=currentProfile)
    logger_to_launch = loadLogger(settings_to_launch)

    jobs = []
    from multiprocessing import Process
    for n in xrange(len(params)):
        p = Process(name="Process-"+str(n), target=gen, args=(logger_to_launch, settings_to_launch, params[n], ))
        jobs.append(p)
        p.start()

    # for i in jobs:
    #     i.join()
