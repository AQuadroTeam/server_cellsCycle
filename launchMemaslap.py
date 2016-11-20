import boto3
def launchMemaslap(settings):
  awsProfileName = settings.getAwsProfileName()
  ec2 = boto3.Session(profile_name=awsProfileName).resource('ec2')

  imageIdCellCycle = "ami-4709cc28"
  keyName = settings.getAwsKeyName()
  securityGroup = settings.getAwsSecurityGroup()
  privateIp = "172.31.21.1"
  userData = 'echo "alias memaslap-test="memaslap -s 172.31.20.1:5555,172.31.20.2:5555,172.31.20.3:5555,172.31.20.4:5555,172.31.20.5:5555"" >> /home/ubuntu/.bashrc\necho "\n\nUse memaslap-test to load system (on 172.31.20.1-5)\nUsage:\n\tmemaslap-test\n\tmemaslap-test -t 100s\n>> /home/ubuntu/.bashrc"'
  ec2.create_instances(ImageId=imageIdCellCycle, MinCount=1, MaxCount=1, InstanceType='t2.micro', KeyName=keyName, SecurityGroups=[securityGroup],  PrivateIpAddress=privateIp, UserData = userData)

if __name__ == "__main__":
    import sys
    from start import loadSettings
    if len(sys.argv) == 1:
        settings = loadSettings(currentProfile='default')
    else:
        currentProfile = {}
        currentProfile["profile_name"] = sys.argv[1]
        currentProfile["key_pair"] = sys.argv[2]
        currentProfile["branch"] = ""
        settings = loadSettings(currentProfile)

    launchMemaslap(settings)
