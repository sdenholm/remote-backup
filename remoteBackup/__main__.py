import argparse
import logging
import sys
import os
import time
import yaml

from remoteOperations import RemoteOperations

# the current and root directories
currentDirectory = os.path.dirname(os.path.realpath(__file__))
rootDirectory    = os.path.dirname(os.path.dirname(currentDirectory))

# CHECK: log file can be created
LOG_FILENAME = os.path.join(currentDirectory, "{}.log".format(os.path.basename(__file__)))
logFileDir = os.path.dirname(LOG_FILENAME)
if not os.path.exists(logFileDir):
  raise FileNotFoundError("log directory does not exist: {}".format(logFileDir))

# create a file logger that automatically rotates log files
logging.getLogger("").setLevel(logging.DEBUG)
from logging.handlers import RotatingFileHandler
fileHandler = RotatingFileHandler(filename=LOG_FILENAME, maxBytes=5000000, backupCount=5, encoding="utf-8")
fileHandler.setLevel(logging.DEBUG)
fileHandler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logging.getLogger("").addHandler(fileHandler)


def parseConfigFile(fileLoc: str):
  """
  # Load the data from the <fileLoc> YAML file
  #
  :param fileLoc:
  :return:
  """
  
  # CHECK: file exists
  if not os.path.exists(fileLoc):
    raise FileNotFoundError("Config file not found at: {}".format(fileLoc))
  
  # load the data
  with open(fileLoc, 'r') as f:
    configData = yaml.safe_load(f)
  
  # yaml config file attributes
  attributes = {
    "remoteUsername":       None,
    "remoteIP":             None,
    "remoteDestinationDir": None,
    "localSourceDirs":      None,
    "sshOptions":           ["privateKeyLoc", "sshPort"],
    "rsyncOptions":         ["arguments", "logOutput"],
    "remoteZFSOptions":     ["enable", "poolName", "snapshotLimit", "importPool", "exportPool", "scrubAfterBackup"],
    "remoteLUKSOptions":    ["enable", "containerLoc", "mountName", "mountToRemoteDestinationDir"]
  }


  # CHECK: config data attributes exist
  for attributeName in attributes.keys():
    if configData.get(attributeName, None) is None:
      raise ValueError(f"Config file: {attributeName} is not defined")
    
    # if it has sub-attributes:
    if isinstance(attributes[attributeName], dict):
      for attributeSubName in attributes[attributeName].keys():
        if configData[attributeName].get(attributeSubName, None) is None:
          raise ValueError(f"Config file: {attributeName}.{attributeSubName} is not defined")
      
      # CHECK: no extra config file sub-attributes
      if not len(attributes[attributeName]) == len(configData[attributeName]):
        for attributeSubName in attributes[attributeName].keys():
          del configData[attributeName][attributeSubName]
        raise ValueError(f"Config file: got unknown config file attributes for {attributeName}: {list(configData.keys())}")
  
  
  # CHECK: no extra config file attributes
  if not len(attributes) == len(configData):
    for attributeName in attributes:
      del configData[attributeName]
    raise ValueError(f"Config file: got unknown config file attributes: {list(configData.keys())}")
  
  
  # CHECK: remote and local paths are absolute
  if not os.path.isabs(configData["remoteDestinationDir"]):
    raise ValueError(f"remoteDestinationDir path must be absolute: {configData['remoteDestinationDir']}")
  for dirLoc in configData["localSourceDirs"]:
    if not os.path.isabs(dirLoc):
      raise ValueError(f"localSourceDirs path must be absolute: {dirLoc}")
  
  
  # CHECK: numbers
  #  -SSH port is >= 0
  #  -ZFS snapshot is >=0
  if not isinstance(configData["sshOptions"]["sshPort"], int) or configData["sshOptions"]["sshPort"] < 0:
    raise ValueError("Config file: sshOptions.sshPort must be a number >= 0")
  if configData["remoteZFSOptions"]["enable"]:
    if not isinstance(configData["remoteZFSOptions"]["snapshotLimit"], int) or\
       configData["remoteZFSOptions"]["snapshotLimit"] < 0:
      raise ValueError("Config file: remoteZFSOptions.snapshotLimit must be a number >= 0")
  
  
  # CHECK: bools
  #  -ZFS:   enable, importPool, exportPool, scrubAfterBackup
  #  -LUKS:  enable
  #  -rsync: logOutput
  for zfsKey in ["enable", "importPool", "exportPool", "scrubAfterBackup"]:
    if not isinstance(configData["remoteZFSOptions"][zfsKey], bool):
      raise ValueError(f"Config file: remoteZFSOptions.{zfsKey} must be a boolean")
  for luksKey in ["enable"]:
    if not isinstance(configData["remoteLUKSOptions"][luksKey], bool):
      raise ValueError(f"Config file: remoteLUKSOptions.{luksKey} must be a boolean")
  for rsyncKey in ["logOutput"]:
    if not isinstance(configData["rsyncOptions"][rsyncKey], bool):
      raise ValueError(f"Config file: rsyncOptions.{rsyncKey} must be a boolean")
  
  
  return configData


def backup(**kwargs):
  
  greenText   = lambda text: "\x1b[32m"       + text + "\x1b[0m"
  redText     = lambda text: "\x1b[38;5;196m" + text + "\x1b[0m"
  #blueText    = lambda text: "\x1b[38;5;39m"  + text + "\x1b[0m"
  #yellowText  = lambda text: "\x1b[38;5;226m" + text + "\x1b[0m"
  #boldRedText = lambda text: "\x1b[31;1m"     + text + "\x1b[0m"
  

  # convert boolean True and False to PASS/FAIL
  _convertBoolToStr = lambda boolValue: "[" + (greenText("PASS") if boolValue else redText("FAIL")) + "]"
  
  # load and parse the config data
  logger.info("Parsing the configuration file...")
  configFileLoc = kwargs.get("configFileLoc")
  configData    = parseConfigFile(configFileLoc)
  
  remoteOps = RemoteOperations(configData)
  
  logger.info("Performing initial checks...")
  
  # CHECK: ssh private key exists
  sshKeyExists = os.path.exists(configData["sshOptions"]["privateKeyLoc"])
  logger.info(f"SSH private key exists:            {_convertBoolToStr(sshKeyExists)}")
  if not sshKeyExists:
    sys.exit(1)

  # CHECK: local directories exist
  for i, dirLoc in enumerate(configData["localSourceDirs"]):
    localDirExists = os.path.exists(dirLoc) and os.path.isdir(dirLoc)
    logger.info(f"Local directory [{str(i+1).zfill(3)}] exists:      {_convertBoolToStr(localDirExists)}")
    if not localDirExists:
      sys.exit(1)
  
  # CHECK: can connect to remote machine
  canConnect = remoteOps.canConnectToRemoteMachine()
  logger.info(f"Connect to remote machine:         {_convertBoolToStr(canConnect)}")
  if not canConnect:
    sys.exit(1)
  
  # CHECK: remote directory exists
  remoteDirExists = remoteOps.remoteDirExists()
  logger.info(f"Remote directory exists:           {_convertBoolToStr(remoteDirExists)}")
  if not remoteDirExists:
    sys.exit(1)

  # CHECK: remote directory has a slash at the end
  remoteDirValid = configData['remoteDestinationDir'][-1] == os.path.sep
  logger.info(f"Remote directory valid:            {_convertBoolToStr(remoteDirValid)}")
  if not remoteDirValid:
    sys.exit(1)

  # CHECK: rsync installed on remote machine
  remoteRsyncInstalled = remoteOps.remoteRsyncInstalled()
  logger.info(f"Remote rsync installed:            {_convertBoolToStr(remoteRsyncInstalled)}")
  if not remoteRsyncInstalled:
    sys.exit(1)
  
  
  # CHECK: ZFS
  if configData["remoteZFSOptions"]["enable"]:
    
    # CHECK: if we are going to import the pool, then it shouldn't be online
    if configData["remoteZFSOptions"]["importPool"]:
      poolNotOnline = not remoteOps.isZFSPoolOnline()
      logger.info(f"Remote ZFS pool not online:        {_convertBoolToStr(poolNotOnline)}")
      if not poolNotOnline:
        sys.exit(1)
    
    # CHECK: remote directory is ZFS pool and online
    else:
      remotePoolOnline = remoteOps.isZFSPoolOnline()
      logger.info(f"Remote ZFS pool online:            {_convertBoolToStr(remotePoolOnline)}")
      if not remotePoolOnline:
        sys.exit(1)
      
      
  # CHECK: LUKS
  if configData["remoteLUKSOptions"]["enable"]:
    
    # CHECK: remote container file exists
    containerExists = remoteOps.luksContainerFileExists()
    logger.info(f"Remote LUKS container file exists: {_convertBoolToStr(containerExists)}")
    if not containerExists:
      sys.exit(1)
    
    # CHECK: remote container is not already open
    containerClosed = not remoteOps.isLUKSContainerOpen()
    logger.info(f"Remote LUKS container closed:      {_convertBoolToStr(containerClosed)}")
    if not containerClosed:
      sys.exit(1)
    
    # LUKS: open container
    containerOpen = remoteOps.openLUKSContainer()
    logger.info(f"Open LUKS container:               {_convertBoolToStr(containerOpen)}")
    if not containerOpen:
      sys.exit(1)
    
    # CHECK: if we're mounting the LUKS container:
    if configData["remoteLUKSOptions"]["mountToRemoteDestinationDir"]:
      
      # CHECK: make sure ZFS isn't also being used, as it mounts the ZFS drive itself
      if configData["remoteZFSOptions"]["enable"]:
        logger.error("Invalid configuration: cannot mount LUKS container with ZFS enabled; ZFS does this itself")
        sys.exit(1)
        
      # CHECK: remote directory is empty
      if not remoteOps.isDirectoryEmpty(configData["remoteDestinationDir"]): #len(os.listdir(configData["remoteDestinationDir"])) != 0:
        logger.error(f"Cannot mount LUKS container in non-empty directory: {configData['remoteDestinationDir']}")
        sys.exit(1)
      
      # LUKS: mount container
      containerMounted = remoteOps.mountLUKSContainer()
      logger.info(f"Mount LUKS container:              {_convertBoolToStr(containerMounted)}")
      if not containerMounted:
        sys.exit(1)
  
  
  # ZFS: import pool
  if configData["remoteZFSOptions"]["enable"] and configData["remoteZFSOptions"]["importPool"]:
    importZpool = remoteOps.importZFSPool()
    logger.info(f"Import ZFS pool:                   {_convertBoolToStr(importZpool)}")
    if not importZpool:
      sys.exit(1)
  
  # REPORT: amount of remote disk space
  spaceInfo = remoteOps.getDiskSpaceInfo()
  if spaceInfo is None:
    logger.error("Could not get disk space information")
    sys.exit(1)
  logger.info(f"Disk space before:                 {spaceInfo['used']}/{spaceInfo['total']}")
  
  
  # catch keyboard interrupt for
  #  -rsync
  #  -zfs operations
  try:
    
    # perform rsync
    logger.info("Starting rsync...")
    logger.info("==================================================")
    remoteOps.performRsync()
    logger.info("==================================================")
    
    
    # snapshot operations
    if configData["remoteZFSOptions"]["enable"] and configData["remoteZFSOptions"]["snapshotLimit"] > 0:
      
      # snapshot
      logger.info("Creating ZFS snapshot")
      remoteOps.zfsCreateSnapshot()
      
      # remove snapshots over limit
      snapshotList = remoteOps.zfsGetSnapshots()
      logger.info(f"Snapshot status:                   {len(snapshotList)}/{configData['remoteZFSOptions']['snapshotLimit']}")
      for snapshotIndex in range(len(snapshotList) - configData["remoteZFSOptions"]["snapshotLimit"]):
        logger.info(f"Destroying old ZFS snapshot:       {snapshotList[snapshotIndex]}")
        remoteOps.zfsDestroySnapshot(snapshotList[snapshotIndex])

    # REPORT: amount of remote disk space
    spaceInfo = remoteOps.getDiskSpaceInfo()
    if spaceInfo is None:
      logger.error("Could not get disk space information")
      sys.exit(1)
    logger.info(f"Disk space after:                  {spaceInfo['used']}/{spaceInfo['total']}")
    
    # ZFS: scrub pool
    if configData["remoteZFSOptions"]["enable"] and configData["remoteZFSOptions"]["scrubAfterBackup"]:
      logger.info("Scrubbing ZFS pool...")
      scrubSuccessful = remoteOps.scrubZFSPool()
      logger.info(f"ZFS pool scrub:                    {_convertBoolToStr(scrubSuccessful)}")
      if not scrubSuccessful:
        sys.exit(1)
  
  
  # user aborted rsync or zfs operations
  except KeyboardInterrupt:
    logger.info(f"\n\nOPERATION ABORTED BY USER")
    logger.info(f"Waiting 10 seconds")
    time.sleep(10)
  
  
  # ZFS: export pool
  if configData["remoteZFSOptions"]["enable"] and configData["remoteZFSOptions"]["exportPool"]:
    exportZpool = remoteOps.exportZFSPool()
    logger.info(f"Export ZFS pool:                   {_convertBoolToStr(exportZpool)}")
    if not exportZpool:
      sys.exit(1)

  # LUKS: close container
  if configData["remoteLUKSOptions"]["enable"]:
    
    # if we mounted the container, unmount it
    if configData["remoteLUKSOptions"]["mountToRemoteDestinationDir"]:
      containerUnmounted = remoteOps.unmountLUKSContainer()
      logger.info(f"Unmount LUKS container:            {_convertBoolToStr(containerUnmounted)}")
      if not containerUnmounted:
        sys.exit(1)
    
    containerClosed = remoteOps.closeLUKSContainer()
    logger.info(f"Close LUKS container:              {_convertBoolToStr(containerClosed)}")
    if not containerClosed:
      sys.exit(1)


  
  
  

if __name__ == "__main__":
  #############################################################################
  # Setup arguments
  #############################################################################
  
  # parser
  parser = argparse.ArgumentParser()
  
  # arguments
  parser.add_argument(metavar="operation", type=str, dest="operation",
                      help="operation to carry out")
  parser.add_argument(metavar="config-file", type=str, dest="configFileLoc",
                      help="location of config file")
  
  # optional arguments
  parser.add_argument("--verbose", action="store_true", help="turn on verbose mode")
  parser.set_defaults(verbose=False)
  
  #############################################################################
  # Process arguments
  #############################################################################
  
  # parse the arguments
  args = parser.parse_args()
  
  # Setup console logger
  #  -verbose turns on DEBUG messages
  console = logging.StreamHandler()
  console.setLevel(logging.DEBUG if args.verbose else logging.INFO)
  console.setFormatter(logging.Formatter("%(message)s"))
  logging.getLogger("").addHandler(console)
  logger = logging.getLogger(__name__)


  #############################################################################
  # Perform operation
  #############################################################################

  if args.operation == "backup":
    backup(**vars(args))
  
  else:
    logger.error(f"Unknown operation: {args.operation}")
  
  sys.exit(0)
