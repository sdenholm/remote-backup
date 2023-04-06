
import os
import pexpect
import getpass
import time
import datetime
import platform
import subprocess
import logging
logger = logging.getLogger(__name__)


class RemoteOperations:
  
  @staticmethod
  def runCommand(cmdList: list, basicCMD=True, useShell=None, outputToStdout=False) -> dict:
    """
    # Run the command and return a dictionary of stdout and stderr
    # Note: for more involved commands, use the "Popen" version
    #
    :param cmdList:        (list) containing command and its arguments
    :param basicCMD:       (bool) to use basic subprocess version, or less secure Popen
    :param useShell:       (bool) use less secure shell, usually needed for interactive
    :param outputToStdout: (bool) by default we capture and return stdout
    :return:
    """
    
    if outputToStdout:
      stdOut = None
    else:
      stdOut = subprocess.PIPE
    
    # simple commands
    if basicCMD:
      
      # windows needs shell
      shell = useShell or platform.system().lower() == "windows"
      
      # run command
      ret = subprocess.run(cmdList, stdout=stdOut, stderr=subprocess.PIPE, shell=shell)
      
      # return stdout and stderr
      return {
        "stdout": "" if stdOut is None else ret.stdout.decode("utf-8"),
        "stderr": ret.stderr.decode("utf-8")
      }
    
    else:
      
      # run command
      ret = subprocess.Popen(" ".join(cmdList), shell=True,
                             stdout=stdOut, stderr=subprocess.PIPE).communicate()
      
      # return stdout and stderr
      return {
        "stdout": "" if stdOut is None else ret[0].decode("utf-8"),
        "stderr": ret[1].decode("utf-8")
      }
  
  
  def _assembleRemoteCommandList(self, command:str) -> list:
    """
    # Assemble the list for an SSH remote command
    #
    :param command:
    :return:
    """
    return [
      "ssh",
      "-p", str(self.sshPort),
      "-i", self.sshPrivateKey,
      f"{self.remoteUsername}@{self.remoteIP}",
      f"'{command}'"
    ]


  def _remoteFileExists(self, fileLocation) -> bool:
    """
    # If a remote file exists
    :return:
    """
    remoteCmd = self._assembleRemoteCommandList(f"ls -lah {fileLocation}")
    cmdOutput = RemoteOperations.runCommand(remoteCmd, basicCMD=False)
    return "No such file or directory" not in cmdOutput["stderr"]
  
  
  def _waitForZFSScrubToComplete(self):
    """
    # Wait for the current scrub of the pool to complete
    #  -periodically check the scrub status, sleeping inbetween
    :return:
    """
  
    # default, minimum and maximum times to sleep
    SLEEP_DEFAULT = datetime.timedelta(minutes=1)
    SLEEP_MIN_TIME = datetime.timedelta(minutes=1)
    SLEEP_MAX_TIME = datetime.timedelta(minutes=60)
  
    # sleep when we have no estimate
    SLEEP_NO_ESTIMATE = datetime.timedelta(minutes=1)
  
    # allowed difference between successive time estimates for us to trust its guess
    ACCEPTED_TIME_DIFFERENCE = datetime.timedelta(minutes=2)
  
    # when we have a completion estimate, how much of this time should we wait
    # before waking up to check teh status again
    #  -e.g., 20% of the remaining time estimate
    SLEEP_PERCENT_REMAINING_TIME = 20
  
    sleepTime = SLEEP_DEFAULT
    lastTimeEstimate = datetime.timedelta(seconds=0)
  
    while True:
    
      # get information about the current scrub
      poolStatus = self._getZFSPoolStatus()
    
      # return if no scrub is taking place
      if not poolStatus["scrub"]["inProgress"]:
        return
    
      # if we don't have a time estimate
      if poolStatus["scrub"]["timeRemaining"] <= datetime.timedelta(seconds=0):
        sleepTime = SLEEP_NO_ESTIMATE
    
      # calculate sleep time based on remaining time
      else:
      
        # see how much the time estimate has changed since we last checked
        #  -takes account for the time we were sleeping
      
        timeEstimateChange = abs((lastTimeEstimate - sleepTime - poolStatus["scrub"]["timeRemaining"]).total_seconds())
      
        # if the time difference between the last and current estimates is more
        # than ACCEPTED_TIME_DIFFERENCE, then don't trust it
        if timeEstimateChange > ACCEPTED_TIME_DIFFERENCE.total_seconds():
          sleepTime = SLEEP_NO_ESTIMATE
      
        # else, sleep for SLEEP_PERCENT_REMAINING_TIME percent of total time remaining
        else:
          estimateSeconds = poolStatus["scrub"]["timeRemaining"].total_seconds()
          sleepTime = datetime.timedelta(seconds=int((SLEEP_PERCENT_REMAINING_TIME / 100) * estimateSeconds))
    
      # remember this sleep estimate
      lastTimeEstimate = poolStatus["scrub"]["timeRemaining"]
    
      # sleep for given time, but more than SLEEP_MAX_TIME and no less than SLEEP_MIN_TIME
      sleepTime = min(SLEEP_MAX_TIME, sleepTime)
      sleepTime = max(SLEEP_MIN_TIME, sleepTime)
    
      wakeTimeStr = (datetime.datetime.utcnow() + sleepTime).replace(microsecond=0)
    
      logger.info(f"Scrub will complete in: {poolStatus['scrub']['timeRemaining']}")
      logger.info(f"Sleeping for: {sleepTime} (until {wakeTimeStr} UTC)")
      time.sleep(sleepTime.total_seconds())
  
  
  def _getZFSPoolStatus(self) -> dict:
    """
    # Return a dictionary describing the status of the ZFS pool
    :return:
    """
  
    poolStatus = {
      "exists": False,
      "isOnline": False,
      # "size": {
      #  "total":  None,
      #  "used":   None,
      # },
      # "errors": {
      #  "read":  None,
      #  "write": None,
      #  "cksum": None,
      # },
      "scrub": {
        "inProgress": False,
        "timeRemaining": datetime.timedelta(),
        # "errors":         None,
        # "completionTime": None
      }
    }
  
    """
      pool: encStorage
     state: ONLINE
      scan: scrub repaired 0B in 00:12:07 with 0 errors on Wed Aug 10 00:12:56 2022
    config:

            NAME                   STATE     READ WRITE CKSUM
            encStorage             ONLINE       0     0     0
              dm-name-encFileDisk  ONLINE       0     0     0

    errors: No known data errors
    """
  
    """
      pool: encStorage
     state: ONLINE
      scan: scrub in progress since Thu Aug 11 19:59:25 2022
            38.6G scanned at 2.57G/s, 252K issued at 16.8K/s, 118G total
            0B repaired, 0.00% done, no estimated completion time
    config:

        NAME                   STATE     READ WRITE CKSUM
        encStorage             ONLINE       0     0     0
          dm-name-encFileDisk  ONLINE       0     0     0

    errors: No known data errors
    """
  
    """
      pool: encStorage
     state: ONLINE
      scan: scrub in progress since Thu Aug 11 19:59:25 2022
            47.6G scanned at 492M/s, 4.15G issued at 43.0M/s, 118G total
            0B repaired, 3.52% done, 00:45:13 to go
    config:

        NAME                   STATE     READ WRITE CKSUM
        encStorage             ONLINE       0     0     0
          dm-name-encFileDisk  ONLINE       0     0     0

    errors: No known data errors
    """
  
    """
    NAME         USED  AVAIL     REFER  MOUNTPOINT
    encStorage   118G  26.4G      115G  /mnt/encStorage
    """
  
    remoteCmd = self._assembleRemoteCommandList(f"zpool status {self.zfsPoolName}")
    cmdOutput = RemoteOperations.runCommand(remoteCmd, basicCMD=False)
  
    # CHECK: got valid status
    if f"pool: {self.zfsPoolName}" not in cmdOutput['stdout']:
      return poolStatus
  
    poolStatus["exists"] = True
    poolStatus["isOnline"] = "state: ONLINE" in cmdOutput['stdout']

    # poolStatus["size"]["total"] = None
    # poolStatus["size"]["used"]  = None

    # poolStatus["errors"]["read"]  = None
    # poolStatus["errors"]["write"] = None
    # poolStatus["errors"]["cksum"] = None
  
    poolStatus["scrub"]["inProgress"] = "scrub in progress" in cmdOutput["stdout"]
    if poolStatus["scrub"]["inProgress"]:
    
      # find and convert the remaining time, if available
      if "no estimated completion time" not in cmdOutput["stdout"]:
        timeParts = list(map(int, cmdOutput["stdout"].split("% done, ")[1].split(" to go")[0].split(":")))
        poolStatus["scrub"]["timeRemaining"] = \
          datetime.timedelta(hours=timeParts[0], minutes=timeParts[1], seconds=timeParts[2])

    # else:
    #  poolStatus["scrub"]["errors"]         = None
    #  poolStatus["scrub"]["completionTime"] = None
  
    return poolStatus
  
  
  def __init__(self, configData: dict):
    """
    #
    :param configData: (dict) data from yaml config file
    """
    self.configData = configData
  
    # remote machine info
    self.remoteUsername = self.configData["remoteUsername"]
    self.remoteIP = self.configData['remoteIP']
    self.remoteDestinationDir = self.configData['remoteDestinationDir']
  
    # local machine info
    self.localSourceDirectories = self.configData['localSourceDirs']
  
    # SSH
    self.sshPort = self.configData["sshOptions"]["sshPort"]
    self.sshPrivateKey = self.configData["sshOptions"]["privateKeyLoc"]
  
    # rsync
    self.rsyncArguments = self.configData["rsyncOptions"]["arguments"]
    self.rsyncLogOutput = self.configData["rsyncOptions"]["logOutput"]
  
    # LUKS
    self.luksMountName = self.configData["remoteLUKSOptions"]["mountName"]
    self.luksContainerLoc = self.configData["remoteLUKSOptions"]["containerLoc"]
    self.luksMountToRemoteDestinationDir = self.configData["remoteLUKSOptions"]["mountToRemoteDestinationDir"]
  
    # ZFS
    self.zfsPoolName = self.configData["remoteZFSOptions"]["poolName"]
  
  
  def isDirectoryEmpty(self, directoryLoc: str) -> bool:
    """
    # Is the given directory empty
    :param directoryLoc:
    :return:
    """
  
    # carry out 'ls <directory>' command
    remoteCmd = self._assembleRemoteCommandList(f"ls {directoryLoc}")
    cmdOutput = RemoteOperations.runCommand(remoteCmd, basicCMD=False)

    # stdOutLines = cmdOutput['stdout'].split("\n")
  
    return len(cmdOutput['stdout']) == 0
  
  
  def isMountedDirectory(self, directoryLoc: str) -> bool:
    """
    # Has a disk been mounted to the directory location
    :param directoryLoc:
    :return:
    """
  
    # get disk info for the directory
    diskInfo = self.getDiskSpaceInfo(directoryToCheck=directoryLoc)
  
    # something has been mounted here if:
    #   -there is SOMETHING here
    #   -the origin of that directory is not /dev/root
    return not (diskInfo is None or "/dev/root" in diskInfo.get("filesystem", ""))
  
  
  def isLUKSContainerOpen(self) -> bool:
    """
    # Is LUKS container open
    :return:
    """
    return self._remoteFileExists(f"/dev/disk/by-id/dm-name-{self.luksMountName}")


  def isZFSPoolOnline(self) -> bool:
    """
    # If the pool exists and is online
    :return:
    """
    poolStatus = self._getZFSPoolStatus()
    return poolStatus.get("isOnline", False)
  
  
  def canConnectToRemoteMachine(self) -> bool:
    """
    # CHECK: can connect to remote machine
    #  -perform "ls /" command on remote machine and do a lazy match (bin, boot, dev)
    #
    :return:
    """
  
    success = True
  
    # perform command on remote machine
    remoteCmd = self._assembleRemoteCommandList("ls /")
    cmdOutput = RemoteOperations.runCommand(remoteCmd, basicCMD=False)
  
    # any connection issues
    if "permission denied" in cmdOutput["stderr"].lower():
      logger.error(f"backup: permission denied when connecting to remote machine: {cmdOutput['stderr']}")
      success = False
  
    else:
    
      # do we get the expected output
      logger.debug(f"canConnectToRemoteMachine: looking at: {cmdOutput['stdout']}")
      for dirName in ["bin", "boot", "dev"]:
        logger.debug(f"canConnectToRemoteMachine: looking for: {dirName}")
        if not dirName in cmdOutput["stdout"]:
          errMsg = f"backup: could not connect to remote machine"
          errMsg += f" (root directory test failed):\n\nstdout:\n"
          errMsg += f"{cmdOutput['stdout']}\n\nstderr:\n{cmdOutput['stderr']}"
          logger.error(errMsg)
          success = False
  
    return success
  
  
  def remoteDirExists(self) -> bool:
    """
    # The remote directory exists
    :return:
    """
    return self._remoteFileExists(self.remoteDestinationDir)
  
  
  def remoteRsyncInstalled(self) -> bool:
    """
    # rsync is installed on the remote machine
    :return:
    """
    remoteCmd = self._assembleRemoteCommandList("whereis rsync")
    cmdOutput = RemoteOperations.runCommand(remoteCmd, basicCMD=False)
    return len(cmdOutput['stdout']) > len("rsync:\n")
  
  
  def getDiskSpaceInfo(self, directoryToCheck=None):
    """
    # Return the result of 'df -h' on the remote directory
    :return:
    """
  
    """
    Filesystem      Size  Used Avail Use% Mounted on
    encStorage      145G  128K  145G   1% /mnt/encStorage
    """
  
    if directoryToCheck is None:
      directoryToCheck = self.remoteDestinationDir
  
    # carry out 'df -h' command
    remoteCmd = self._assembleRemoteCommandList(f"df -h {directoryToCheck}")
    cmdOutput = RemoteOperations.runCommand(remoteCmd, basicCMD=False)
  
    # split result into lines
    stdOutLines = cmdOutput['stdout'].split("\n")
  
    # CHECK: directory is found and found only once
    if "No such file or directory" in cmdOutput['stderr'] or len(stdOutLines) != 3:
      return None
  
    # return: total size and space used
    else:
      diskInfo = [entry for entry in stdOutLines[1].split(" ") if entry != ""]
      return {
        "filesystem": diskInfo[0],
        "total": diskInfo[1],
        "used": diskInfo[2]
      }
    
    
  def performRsync(self) -> bool:
    """
    # rsync local directory to remote directory using SSH
    #
    :return:
    """
  
    # SSH string within rsync command
    sshStr = f"ssh -p {self.sshPort} -i {self.sshPrivateKey}"
  
    # run the rsync command for each source directory
    for localSourceDir in self.localSourceDirectories:
    
      # set up the log file
      if "--log-file=" in self.rsyncArguments:
        logger.info("'log-file option specified in rsync arguments; skipping internal log file")
        arguments = self.rsyncArguments
    
      else:
        currentDT = datetime.datetime.utcnow().strftime("%Y-%m-%d--%H-%M-%S")
        logFilename = "rsync-log--" + currentDT + "--" + localSourceDir.replace(os.path.sep, ".")
        arguments = self.rsyncArguments + f" --log-file='{logFilename}'"
    
      logger.info(f"rsync local directory: {localSourceDir}")
      rsyncCmd = ["rsync", arguments, "-e",
                  f'"{sshStr}"',
                  f"{localSourceDir}",
                  f"{self.remoteUsername}@{self.remoteIP}:{self.remoteDestinationDir}"
                  ]
      cmdOutput = RemoteOperations.runCommand(rsyncCmd, basicCMD=False, outputToStdout=not self.rsyncLogOutput)
    
      # print the error output
      logger.info(cmdOutput['stderr'])
    
      # print the rsync output to the log
      if self.rsyncLogOutput:
        logger.info(cmdOutput['stdout'])
        # if not ("total size is" in cmdOutput['stdout'] and "speedup is" in cmdOutput['stdout']):
        #  return False
  
    return True


  def openLUKSContainer(self) -> bool:
    """
    # Open the LUKS container (by the user entering a password)
    :return:
    """
    
    # send the "open LUKS container" command via SSH
    remoteCmd = self._assembleRemoteCommandList(f"sudo cryptsetup luksOpen {self.luksContainerLoc} {self.luksMountName}")
    child = pexpect.spawn(" ".join(remoteCmd), timeout=60)
    
    # user enters the password, pass this to the shell
    child.sendline(getpass.getpass('LUKS container password: '))
    
    # wait for the command to finish, then close
    child.expect([pexpect.EOF])
    child.close()
    
    # check that the container is now open
    return self.isLUKSContainerOpen()
  
  
  def closeLUKSContainer(self) -> bool:
    """
    # Close the LUKS container
    :return:
    """
    remoteCmd = self._assembleRemoteCommandList(f"sudo cryptsetup luksClose /dev/mapper/{self.luksMountName}")
    RemoteOperations.runCommand(remoteCmd, basicCMD=False)
    return not self.isLUKSContainerOpen()
  
  
  def mountLUKSContainer(self) -> bool:
    """
    # Mount the LUKS container to the remote directory location
    :return:
    """
    
    # send the "mount LUKS container" command via SSH
    remoteCmd = self._assembleRemoteCommandList(f"sudo mount /dev/mapper/{self.luksMountName} {self.remoteDestinationDir}")
    RemoteOperations.runCommand(remoteCmd, basicCMD=False)
    
    # did we mount the container to this location
    return self.isMountedDirectory(self.remoteDestinationDir)
  
  
  def unmountLUKSContainer(self) -> bool:
    """
    # Unmount the LUKS container
    :return:
    """
  
    # send the "unmount LUKS container" command via SSH
    remoteCmd = self._assembleRemoteCommandList(f"sudo umount /dev/mapper/{self.luksMountName}")
    RemoteOperations.runCommand(remoteCmd, basicCMD=False)
  
    # did we unmount the container at this location
    return not self.isMountedDirectory(self.remoteDestinationDir)
    

  def luksContainerFileExists(self) -> bool:
    """
    # The remote LUKS container file exists
    :return:
    """
    return self._remoteFileExists(self.luksContainerLoc)
  
  
  def importZFSPool(self) -> bool:
    """
    # Import the ZFS pool
    :return:
    """
    remoteCmd = self._assembleRemoteCommandList(f"sudo zpool import {self.zfsPoolName}")
    RemoteOperations.runCommand(remoteCmd, basicCMD=False)
    return self.isZFSPoolOnline()


  def exportZFSPool(self) -> bool:
    """
    # Export the ZFS pool
    :return:
    """

    poolStatus = self._getZFSPoolStatus()
    
    # CHECK: pool is online
    if not poolStatus["isOnline"]:
      logger.error("exportZFSPool: cannot export; pool is not online")
      return False

    # CHECK: pool not being scrubbed
    if poolStatus["scrub"]["inProgress"]:
      logger.error("exportZFSPool: cannot export; pool is currently beign scrubbed")
      return False
    
    remoteCmd = self._assembleRemoteCommandList(f"sudo zpool export {self.zfsPoolName}")
    RemoteOperations.runCommand(remoteCmd, basicCMD=False)
    return not self.isZFSPoolOnline()
  

  def scrubZFSPool(self, blocking=True) -> bool:
    """
    # Start a scrub of the ZFS pool
    #
    :param blocking: (bool) wait until the scrub completes
    :return:
    """
    
    # get full pool status
    poolStatus = self._getZFSPoolStatus()
    
    # CHECK: pool is online
    if not poolStatus["isOnline"]:
      logger.error("scrubZFSPool: pool is not online")
      return False
    
    # CHECK: scrub not already taking place
    if poolStatus["scrub"]["inProgress"]:
      logger.error("scrubZFSPool: cannot scrub pool as scrub already in progress")
      return False
    
    # perform the scrub
    remoteCmd = self._assembleRemoteCommandList(f"sudo zpool scrub {self.zfsPoolName}")
    RemoteOperations.runCommand(remoteCmd, basicCMD=False)
    
    # wait, if we want to wait
    if blocking:
      self._waitForZFSScrubToComplete()
    
    return True
    

  def zfsGetSnapshots(self) -> list:
    """
    # Get a list of all the snapshots for our pool
    :return:
    """
  
    """
    NAME                              USED  AVAIL     REFER  MOUNTPOINT
    encStorage@2022-08-08--01-07-27     0B      -       96K  -
    encStorage@2022-08-08--01-10-31     0B      -       96K  -
    """
  
    """
    no datasets available
    """
  
    # list the zfs snapshots
    remoteCmd = self._assembleRemoteCommandList("zfs list -t snapshot")
    cmdOutput = RemoteOperations.runCommand(remoteCmd, basicCMD=False)
  
    # if no snapshots for our pool, or no snapshots at all
    if self.zfsPoolName not in cmdOutput['stdout'] or \
        "no datasets available" in cmdOutput['stdout']:
      return []
  
    # isolate just the snapshots for our pool, and separate the output lines
    snapshotLines = [line for line in cmdOutput['stdout'].split("\n")[1:] if f"{self.zfsPoolName}@" in line]
  
    # return just the name of the snapshots
    return [name.split(" ")[0] for name in snapshotLines]
  
  
  def zfsCreateSnapshot(self) -> bool:
    """
    # Create a snapshot of the remote ZFS pool
    :return:
    """
    
    # snapshot name will just be <pool name>@datetime
    snapshotName = datetime.datetime.utcnow().strftime("%Y-%m-%d--%H-%M-%S")
    commandStr = f"sudo zfs snapshot {self.zfsPoolName}@{snapshotName}"

    remoteCmd = self._assembleRemoteCommandList(commandStr)
    RemoteOperations.runCommand(remoteCmd, basicCMD=False)
    return True


  def zfsDestroySnapshot(self, snapshotName: str) -> bool:
    """
    # Destroy a ZFS snapshot
    #
    :param snapshotName:
    :return:
    """
  
    # CHECK: will only destroy a snapshot
    if "@" not in snapshotName:
      logger.error(f"tried to destroy something that wasn't a snapshot: {snapshotName}")
      raise SystemError(f"tried to destroy something that wasn't a snapshot: {snapshotName}")

    remoteCmd = self._assembleRemoteCommandList(f"sudo zfs destroy {snapshotName}")
    RemoteOperations.runCommand(remoteCmd, basicCMD=False)
    return True
  

    