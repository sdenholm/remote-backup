# Remote Backup
- [General Idea](#general-idea)
- [(Optional) Remote System Setup](#optional-remote-system-setup)
- [Application](#application)

## General Idea 

1. Remote linux machine acts as a backup for local directories.
2. Backup is (optionally) configured as a ZFS pool that sits on top of an encrpted LUKS disk.
3. The application is run on the local machine to back up a list of local directories to the remote machine over SSH, using rsync.
4. We will also take a ZFS snapshot (if applicable), maintaining no more than __X__ snapshots by detroying the oldest ones. 

## (Optional) Remote System Setup

In this section we create a ZFS pool on top of a LUKS encrypted disk. All operations are performed on the __remote__ machine.

___
### Create and initialise the file system

Install encryption package and ZFS:
```bash
sudo apt install cryptsetup zfsutils-linux
```

Create an empty (size 0) file for the new, encrypted file system of size 20G:
```bash
sudo dd if=/dev/zero of=encFile.img bs=1 count=0 seek=20G
```

Initialise the LUKS partition in the new, empty file:
```bash
sudo cryptsetup luksFormat -q -c aes-xts-plain64 -s 512 -h sha512 encFile.img
```

Open the file and map it to _/dev/mapper/encFileDisk_:
```bash
sudo cryptsetup luksOpen encFile.img encFileDisk
```

Create a mounting directory for the new zpool:
```bash
sudo mkdir /mnt/encStorage
sudo chown $USER:$USER /mnt/encStorage
```

Format the newly opened disk and import it:
```bash
sudo zpool create -o ashift=12 -m /mnt/encStorage encStorage /dev/disk/by-id/dm-name-encFileDisk
```

__OTHER__: If wanting to just format it with ext4:
```bash
sudo mkfs -t ext4 /dev/disk/by-id/dm-name-encFileDisk
```
<br>

__OPTIONAL__: Schedule a zpool scrub on the 15th of every month at 04:00. In ```crontab -e```:
```bash
0 4 15 * * sudo /usr/sbin/zpool scrub encStorage
```

___
### Open the file system

Open the file and map it to _/dev/mapper/encFileDisk_:
```bash
sudo cryptsetup luksOpen encFile.img encFileDisk
```

Import the newly opened disk:
```bash
sudo zpool import encStorage
```
___
### Close the file system

Export the pool and close the encrypted container:
```bash
sudo zpool export encStorage
sudo cryptsetup luksClose /dev/mapper/encFileDisk
```

___
### Managing Encrypted Containers

Get information about a LUKS container:
```bash
sudo cryptsetup luksDump encFile.img
```

Backup a LUKS container's header:
```bash
sudo cryptsetup luksHeaderBackup encFile.img --header-backup-file backupfile.header
```

Restore a LUKS container's header:
```bash
sudo cryptsetup luksHeaderRestore encFile.img --header-backup-file backupfile.header
```


## Application

In this section we set up the actual backup application. All commands and operations occur on the __local__ machine, and the user must have password-less sudo access enabled on the __remote__ machine.

The program uses rsync to copy a list of _local directories_ into a _remote directory_ over SSH

If using LUKS containers, we can (optionally):
- open a LUKS container before backup, and close it afterwards; this requires the user to manually enter the password

If using ZFS pools, we can (optionally):
- import a ZFS pool before backup
- export a pool after backup completes
- scrub the ZFS pool after backup
- create a snapshot after backup is complete, maintaining a maximum number of snapshots by destroying older snapshots

___
### Installation

Install the Python requirements:
```bash
pip3 install -r requirements.txt
```

Create the yaml config file based on the example template. Use of the ZFS and LUKS features can be enabled/disabled here:
```yaml
# username on remote machine
remoteUsername: ubuntu

# IP of remote machine
remoteIP: 192.168.1.2

# remote location to rsync data INTO
#  -path must be absolute
remoteDestinationDir: /mnt/encStorage/

# local directories to copy to the remote machine
#  -path must be absolute
#  -be careful about trailing slashes...
#    -slash:    copy contents of directory
#    -no slash: copy directory
localSourceDirs:
  - /path/to/local/dir

# options for SSH connection to remote machine
sshOptions:

  # local location of private key to ssh into the remote machine
  privateKeyLoc: /local/path/to/private.key

  # SSH port to use
  sshPort: 22

# options for rsync
rsyncOptions:

  # arguments for rsync command
  arguments: -arvv --delete

  # do we want to log the output of rsync
  logOutput: false

# options for working with a ZFS pool on the remote machine
remoteZFSOptions:

  # enable this feature
  enable: true

  # name of the ZFS pool
  poolName: encStorage

  # number of ZFS snapshots to maintain
  snapshotLimit: 5

  # import pool before backup
  #  -useful if using automated LUKS options
  importPool: true

  # export pool after backup
  #  -useful if using automated LUKS options
  exportPool: true
  
  # scrub the pool after backup completes
  scrubAfterBackup: false

# options for working with an encrypted LUKS container on the remote machine
remoteLUKSOptions:

  # enable this feature
  enable: true

  # remote location of LUKS container to open
  containerLoc: /remote/location/of/disk.img

  # name of mounted LUKS container
  mountName: encFileDisk

  # should we mount the container to the remoteDestinationDir
  #  -ZFS does this, so only use if LUKS = true and ZFS = false
  mountToRemoteDestinationDir: false
```

___
### Use

Perform the backup operation using the _config.yaml_ file:
```bash
python3 remoteBackup backup config.yaml
```

An rsync log file is generated for each of the _localSourceDirs_ entries. This feature is disabled if the ```--log-file``` flag is defined in the __rsyncOptions.arguments__ variable of the configuration file.
