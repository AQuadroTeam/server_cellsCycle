import Queue
from multiprocessing import Process
from cPickle import loads, dumps
from threading import Thread
import zmq
from time import time, sleep
from CellCycle.MemoryModule.Cache import CacheSlubLRU
from CellCycle.ChainModule.ListThread import ListThread
from CellCycle.ChainModule.ListCommunication import InternalChannel

SETCOMMAND = 0
GETCOMMAND = 1
SHUTDOWNCOMMAND = -1
TRANSFERMEMORY = 2
NEWMASTER = 3
TRANSFERCOMPLETE = 4
NEWSLAVE = 5
NEWSTART = 6

def startMemoryTask(settings, logger, master):

    url_getBackend = "inproc://get_memory" + ("master" if master else "slave")
    url_setBackend = "inproc://set_memory" + ("master" if master else "slave")
    url_setFrontend = "tcp://*:" + str(settings.getMasterSetPort() if master else settings.getSlaveSetPort())
    url_getFrontend = "tcp://*:" + str(settings.getMasterGetPort() if master else settings.getSlaveGetPort())

    #create new process
    processName = "python-CCMemoryMaster" if master else "python-CCMemorySlave"
    p = Process(name=processName,target=_memoryTask, args=(settings, logger,master, url_setFrontend, url_getFrontend, url_getBackend, url_setBackend))
    p.start()

    return url_getBackend, url_setBackend, url_setFrontend, url_getFrontend


def _memoryTask(settings, logger,master, url_setFrontend, url_getFrontend, url_getBackend, url_setBackend):
    from Cache import Slab, CacheSlubLRU
    # grab settings
    slabSize = settings.getSlabSize()
    preallocatedPool = settings.getPreallocatedPool()
    getterNumber = settings.getGetterThreadNumber()

    # initialize cache
    cache = CacheSlubLRU(preallocatedPool , slabSize, logger) #set as 10 mega, 1 mega per slab

    #log
    logger.debug("Memory Process initialized:" + str(preallocatedPool) + "B, get# = " + str(getterNumber))

    # Prepare our context and sockets
    context = zmq.Context.instance()
    # Socket to talk to get
    socketGetFrontend = context.socket(zmq.ROUTER)
    socketGetFrontend.bind(url_getFrontend)

    # Socket to talk to workers
    socketGetBackend = context.socket(zmq.DEALER)
    socketGetBackend.bind(url_getBackend)

    timing = {}
    timing["getters"] = []
    timing["setters"] = [-1]

    Thread(name='MemoryGetProxy',target=_proxyThread, args=(logger, master, socketGetFrontend, socketGetBackend, url_getFrontend, url_getBackend)).start()

    for i in range(getterNumber):
        timing["getters"].append(-1)
        th = Thread(name='MemoryGetter',target=_getThread, args=(i,logger, settings, cache,master,url_getBackend, timing))
        th.start()

    slaveSetQueue = Queue.Queue()
    hostState = None

    Thread(name='MemoryPerformanceMetricator',target=_memoryMetricatorThread, args=(logger, cache, settings, master, timing)).start()
    Thread(name='MemorySlaveSetter',target=_setToSlaveThread, args=(logger,settings, cache,master,url_getBackend, slaveSetQueue, hostState)).start()

    _setThread(logger, settings, cache,master,url_setFrontend,slaveSetQueue, hostState, timing)


def _memoryMetricatorThread(logger, cache, settings, master, timing):
    if master:
        period = settings.getScalePeriod()

        setScaleDownLevel   = settings.getSetScaleDownLevel()   if settings.getSetScaleDownLevel()  >0 else -float("inf")
        setScaleUpLevel     = settings.getSetScaleUpLevel()     if settings.getSetScaleUpLevel()    >0 else  float("inf")
        getScaleDownLevel   = settings.getGetScaleDownLevel()   if settings.getGetScaleDownLevel()  >0 else -float("inf")
        getScaleUpLevel     = settings.getGetScaleUpLevel()     if settings.getGetScaleUpLevel()    >0 else  float("inf")

        logger.debug("Metricator alive, period: "+ str(period) +"s, getThrLevel: [" +str(getScaleDownLevel) +"," + str(getScaleUpLevel)+ "], setThrLevel: [" + str(setScaleDownLevel) + "," + str(setScaleUpLevel) + "]"  )

        # this channel is necessary to send scale up/down requests
        internal_channel = InternalChannel(addr='127.0.0.1', port=settings.getIntPort(), logger=logger)
        internal_channel.generate_internal_channel_client_side()

        while True:
            sleep(period)
            setMean = 1.0 - timing["setters"][0].calcMean()
            getMean = 0.0
            for metr in timing["getters"]:
                getMean += 1.0 - metr.calcMean()
            getMean = getMean / settings.getGetterThreadNumber()

            logger.debug("Working time for setters: " + str(setMean) + ", getters (mean): " + str(getMean) )

            # scale up needed
            if getMean >= getScaleUpLevel or setMean >= setScaleUpLevel:
                logger.debug("Requests for scale Up!")
                # call scale up service
                ListThread.notify_scale_up(internal_channel)
                # self.list_communication_thread.notify_scale_up()

            # scale down needed
            elif getMean <= getScaleDownLevel or setMean <= setScaleDownLevel:
                logger.debug("Requests for scale Down!")
                # Tcall scale down service
                ListThread.notify_scale_down(internal_channel)
                # self.list_communication_thread.notify_scale_down()


def _proxyThread(logger, master, frontend, backend, url_frontend, url_backend):
    logger.debug("Routing from " + url_frontend + " to " + url_backend)
    zmq.proxy(frontend, backend)

def _setToSlaveThread(logger,settings,  cache, master,url, queue, hostState):
    import time
    while (hostState == None):
        time.sleep(1)
    while True:
        logger.debug("Start to send to my slave: " + str(hostState.slave.ip))
        objToSend = queue.get()
        slaveAddress = "tcp://"+hostState.slave.ip + ":"+ str(settings.getSlaveSetPort())
        if(slaveAddress != None):
            try:
                setRequest(slaveAddress, objToSend.key, objToSend.value)
            except Exception as e:
                logger.warning(str(e))

def _setThread(logger, settings, cache, master, url,queue,  hostState, timing):
    logger.debug("Listening in new task for set on " + url)
    context = zmq.Context.instance()
    socket = context.socket(zmq.PULL)
    socket.bind(url)

    internal_channel_added = InternalChannel(addr="localhost", port=settings.getMemoryObjectPort(), logger=logger)
    internal_channel_added.generate_internal_channel_client_side()

    internal_channel_restored = InternalChannel(addr="localhost", port=settings.getIntPort(), logger=logger)
    internal_channel_restored.generate_internal_channel_client_side()

    transferToDoAfter = False

    if master:
        timing["setters"] = []
        timing["setters"].append(TimingMetricator())

    while True:
        try:
            if master:
                timing["setters"][0].startWaiting()

            command = loads(socket.recv())
            if master:
                timing["setters"][0].startWorking()

            #logger.debug("received set command: " + str(command))
            if command.type == SETCOMMAND:
                queue.put(Command(command.type, command.key, command.value))
                cache.set(command.key, command.value)
            elif command.type == SHUTDOWNCOMMAND:
                logger.debug("shutdown command")
                import os, signal
                os.kill(os.getpid(), signal.SIGTERM)
                return
            elif command.type == TRANSFERMEMORY:
                for address in command.address:
                    logger.debug("Transferring memory to " + str(address) + "....")
                    dest = address
                    dataList = cache.cache.iteritems()
                    begin = command.optional[0]
                    end = command.optional[1]
                    _transfer(dest, dataList, begin, end)
                    logger.debug("Transfer complete!")

            elif command.type == NEWMASTER:
                if(hostState == None):
                    logger.debug("Configuration of net data: "+ str(hostState))
                    hostState = command.optional
                else:
                    logger.warning("master is dead. Recovering... "+ str(hostState))
                    hostState = command.optional
                    # import keys of master, from this slave memory
                    thisMasterMemory = "tcp://localhost:"+ str(settings.getMasterSetPort())
                    thisSlaveMemory = "tcp://localhost:"+ str(settings.getSlaveSetPort())
                    newSlaveSlaveMemory =  "tcp://"+hostState.slave.ip+":"+ str(settings.getSlaveSetPort())
                    beginFirst = hostState.myself.min_key #command.optional.thisnode.slave.keys.begin oldone!
                    endFirst = hostState.myself.max_key #command.optional.thisnode.slave.keys.end oldone!
                    transferRequest(thisSlaveMemory, [thisMasterMemory, newSlaveSlaveMemory], beginFirst, endFirst)

                    # create new slave memory for this node from new master
                    newMasterMasterMemory = "tcp://"+ hostState.master.ip +":"+ str(settings.getMasterSetPort())
                    # instead of localhost i must have command.optional.newmaster.url
                    thisSlaveMemory = "tcp://localhost:"+ str(settings.getSlaveSetPort())
                    beginSecond = hostState.master.min_key #command.optional.newmaster.master.keys.begin
                    endSecond = hostState.master.max_key #command.optional.newmaster.master.keys.end
                    transferRequest(newMasterMasterMemory,[thisSlaveMemory],  beginSecond, endSecond)

                    transferToDoAfter = True
                    transferType = NEWMASTER

            elif command.type == NEWSLAVE:
                logger.debug("Slave is dead, new info: "+ str(hostState))
                hostState = command.optional

            elif command.type == NEWSTART:
                logger.debug("Memory needs to be configured, first bootup of this memory node, new info: "+ str(hostState))
                hostState = command.optional
                # import keys of master
                thisMasterMemory = "tcp://localhost:"+ str(settings.getMasterSetPort())
                thisSlaveMemory = "tcp://localhost:"+ str(settings.getSlaveSetPort())
                masterMasterMemory =  "tcp://"+hostState.master.ip+":"+ str(settings.getMasterSetPort())

                beginFirst = hostState.myself.min_key #command.optional.thisnode.slave.keys.begin oldone!
                endFirst = hostState.myself.max_key #command.optional.thisnode.slave.keys.end oldone!

                beginSlave = hostState.master.min_key #command.optional.thisnode.slave.keys.begin oldone!
                endSlave = hostState.master.max_key #command.optional.thisnode.slave.keys.end oldone!

                transferRequest(masterMasterMemory, thisMasterMemory, beginFirst, endFirst)
                transferRequest(masterMasterMemory, thisSlaveMemory, beginSlave, endSlave)

                transferToDoAfter = True
                transferType = NEWSTART

            elif command.type == TRANSFERCOMPLETE:
                if transferToDoAfter and master:
                    # call the list communication for added or recovered
                    if transferType == NEWSTART:
                        internal_channel_added.send_first_internal_channel_message(message="FINISHED")
                        internal_channel_added.wait_int_message(dont_wait=False)
                    elif transferType == NEWMASTER:
                        ListThread.notify_restored(internal_channel_restored)
                    #avvertire gestore ciclo che E finito recovery TODO:
                    logger.warning("new master state recovery: DONE")
                    #do something with command and hostState
                    #command.optional --> hostState
                    transferToDoAfter = False

            if master:
                timing["setters"][0].stopWorking()
        except Exception as e:
            logger.error(e)

def _transfer(dest, dataList, begin, end):
    context = zmq.Context.instance()
    socketTM = context.socket(zmq.PUSH)

    socketTM.connect(dest)
    for data in dataList:
        key = int(data[0])
        if(key >= int(begin) and  key <= int(end) ):
            value = data[1].getValue(key)
            print "transferring:" +str(value) #it's just for debug TODO to delete
            socketTM.send(dumps(Command(SETCOMMAND,key,value)))
    socketTM.send(dumps(Command(TRANSFERCOMPLETE)))
    socketTM.close()

def _getThread(index, logger,settings, cache, master, url, timing):
    logger.debug("Listening in new task for get on " + url)
    context = zmq.Context.instance()
    socket = context.socket(zmq.REP)
    socket.connect(url)

    if master:
        timing["getters"][index] = TimingMetricator()

    while True:
        try:
            if master:
                timing["getters"][index].startWaiting()
            command = loads(socket.recv())
            if master:
                timing["getters"][index].startWorking()

            #logger.debug( "received get command: " + str(command))
            if command.type == GETCOMMAND:
                v=cache.get(command.key)
                socket.send(dumps(v))
            #if command.type == SHUTDOWNCOMMAND:
            #    return
            if master:
                timing["getters"][index].stopWorking()
        except Exception as e:
            logger.error(e)

# client operations
def getRequest(url, key):
    context = zmq.Context.instance()
    socket = context.socket(zmq.REQ)
    socket.connect(url)

    socket.send(dumps(Command(GETCOMMAND, key)))
    v = loads(socket.recv())
    socket.close()
    return v

def setRequest(url, key, value):
    context = zmq.Context.instance()
    socket = context.socket(zmq.PUSH)
    socket.connect(url)

    socket.send(dumps(Command(SETCOMMAND, key, value)))
    socket.close()

def killProcess(url):
    context = zmq.Context.instance()
    socket = context.socket(zmq.PUSH)
    socket.connect(url)

    socket.send(dumps(Command(SHUTDOWNCOMMAND)))
    socket.close()

def transferRequest(url, dest, begin, end):
    context = zmq.Context.instance()
    socket = context.socket(zmq.PUSH)
    socket.connect(url)

    socket.send(dumps(Command(TRANSFERMEMORY, address=dest, optional=(begin,end))))
    socket.close()
"""
usage:
    from MemoryModule.MemoryManagement import newMasterRequest
    import zmq
    newMasterRequest("tcp://localhost:" + str(settings.getMasterSetPort()), hostInformations)
"""
def newMasterRequest(url, hostInformations):
    context = zmq.Context.instance()
    socket = context.socket(zmq.PUSH)
    socket.connect(url)
    command = Command(NEWMASTER)
    command.optional = hostInformations
    socket.send(dumps(command))
    socket.close()

"""
usage:
    from MemoryModule.MemoryManagement import newSlaveRequest
    import zmq
    newSlaveRequest("tcp://localhost:" + str(settings.getMasterSetPort()), hostInformations)
"""
def newSlaveRequest(url, hostInformations):
    context = zmq.Context.instance()
    socket = context.socket(zmq.PUSH)
    socket.connect(url)
    command = Command(NEWSLAVE)
    command.optional = hostInformations
    socket.send(dumps(command))
    socket.close()

"""
usage:
    from MemoryModule.MemoryManagement import newStartRequest
    import zmq
    newStartRequest("tcp://localhost:" + str(settings.getMasterSetPort()), hostInformations)
"""
def newStartRequest(url, hostInformations):
    context = zmq.Context.instance()
    socket = context.socket(zmq.PUSH)
    socket.connect(url)
    command = Command(NEWSTART)
    command.optional = hostInformations
    socket.send(dumps(command))
    socket.close()

def standardnewMasterRequest(settings, hostInformations, host="localhost"):
    url_setPort = "tcp://"+host+":" + str(settings.getMasterSetPort())
    return newMasterRequest(url_setPort, hostInformations)

def standardMasterSetRequest(settings, key, value, host="localhost"):
    url_setPort = "tcp://"+host+":" + str(settings.getMasterSetPort())
    return setRequest(url_setPort, key, value)

def standardMasterGetRequest(settings, key, host="localhost"):
    url_getPort = "tcp://"+host+":" + str(settings.getMasterGetPort())
    return getRequest(url_getPort, key)

def standardSlaveSetRequest(settings, key, value, host="localhost"):
    url_setPort = "tcp://"+host+":" + str(settings.getSlaveSetPort())
    return setRequest(url_setPort, key, value)

def standardSlaveGetRequest(settings, key, host="localhost"):
    url_getPort = "tcp://"+host+":" + str(settings.getSlaveGetPort())
    return getRequest(url_getPort, key)

def standardKillRequest(settings, host="localhost"):
    url_setPort = "tcp://"+host+":" + str(settings.getMasterSetPort())
    return killProcess(url_setPort)

def standardTransferRequest(settings, dest="localhost", host="localhost"):
    url_setPort = "tcp://"+host+":" + str(settings.getMasterSetPort())
    dest = "tcp://"+dest+":" + str(settings.getSlaveSetPort())
    return transferRequest(url_setPort, [dest], 0,99999999999999)

class Command(object):
    def __init__(self, type, key=None, value=None, address=[], optional=None):
        self.type = int(type)
        self.key = key
        self.value = value
        self.address = address
        self.optional = optional
    def __str__(self):
        return "type: "+ str(self.type) + ", key: "+ str(self.key) + ", value: " + str(self.value)



# only for benchamrk
def startMemoryTaskForTrial(preallocatedPool, slabSize, logger, pipe_set, pipe_get):

    cache = CacheSlubLRU(preallocatedPool , slabSize, logger) #set as 10 mega, 1 mega per slab
    for pipe in pipe_get:
        th = Thread(target=_getThread, args=(cache, pipe))
        th.start()

    _setThread(cache, pipe_set)

class TimingMetricator(object):
    """docstring forTimingMetricator."""
    def __init__(self):
        self.startWaitingTime = 0
        self.startWorkingTime = 0
        self.stopWorkingTime = 0
        self.meanWaitingRatio = 0
        self.totalWorkingTime = 0
        self.startPeriod = time()

    def __str__(self):
        return str(self.getMean())

    def getMean(self):
        return self.meanWaitingRatio

    def startWorking(self):
        self.startWorkingTime = time()

    def startWaiting(self):
        self.startWaitingTime = time()

    def calcMean(self):
        period = time() - self.startPeriod
        working = self.totalWorkingTime
        waitingMean = 1 - (working / float(period))
        self.totalWorkingTime = 0
        self.startPeriod = time()
        self.meanWaitingRatio = waitingMean
        return waitingMean

    def stopWorking(self):
        self.stopWorkingTime = time()
        work = self.stopWorkingTime - self.startWorkingTime
        self.totalWorkingTime += work
