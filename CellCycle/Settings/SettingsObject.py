# All info at https://github.com/AQuadroTeam/CellsCycle/wiki/Settings
import Constants

class SettingsObject:

    def __init__(self, dict):
        self.configDict = dict

    # log settings
    def getLogFile(self):
        return self.configDict[Constants.LOGFILE][0]

    def isVerbose(self):
        return True if self.configDict[Constants.VERBOSE][0] == "True" else False
    # end of log settings

    # memory settings
    def getSlabSize(self):
        return int(self.configDict[Constants.SLABSIZE][0])

    def getPreallocatedPool(self):
        return int(self.configDict[Constants.PREALLOCATEDPOOL][0])

    def getGetterThreadNumber(self):
        return int(self.configDict[Constants.GETTERTHREADNUMBER][0])

    def __str__(self):
        string = "Configuration:\n"
        for (key,value) in self.configDict.iteritems() :
            string += key + " : " + str(value) + "\n"
        string += "End Of Configuration\n"
        return string
    # end of memory settings


    def printAll(self):
        print self
