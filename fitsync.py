import httplib2
import sys
import time
import yaml

import fitbit
from apiclient.discovery import build
from oauth2client.file import Storage
from oauth2client.client import OAuth2Credentials
from googleapiclient.errors import HttpError


POUNDS_PER_KILOGRAM = 2.20462

TIME_FORMAT = "%a, %d %b %Y %H:%M:%S"


def GetFitbitClient():
  credentials = yaml.load(open('fitbit.yaml'))
  client = fitbit.Fitbit(**credentials)
  return client


def GetGoogleClient():
  credentials = Storage('google.json').get()
  http = credentials.authorize(httplib2.Http())
  client = build('fitness', 'v1', http=http)
  return client


def nano(val):
  """Converts a number to nano (str)."""
  return '%d' % (val * 1e9)


def FitbitWeightToGoogleWeight(fitbitWeightLog):
  logSecs = fitbitWeightLog['logId'] / 1000
  logWeightLbs = fitbitWeightLog['weight']
  logWeightKg = logWeightLbs / POUNDS_PER_KILOGRAM
  return dict(
    dataTypeName='com.google.weight',
    endTimeNanos=nano(logSecs),
    startTimeNanos=nano(logSecs),
    value=[dict(fpVal=logWeightKg)],
  )


def GetDataSourceId(dataSource):
  projectNumber = Storage('google.json').get().client_id.split('-')[0]
  return ':'.join((
    dataSource['type'],
    dataSource['dataType']['name'],
    projectNumber,
    dataSource['device']['manufacturer'],
    dataSource['device']['model'],
    dataSource['device']['uid']))


def main():
  fitbitClient = GetFitbitClient()

  devices = fitbitClient.get_devices()
  (scale,) = (device for device in devices if device['type'] == 'SCALE')

  fitbitBodyweight = fitbitClient.get_bodyweight(period='30d')
  fitbitWeightLogs = fitbitBodyweight['weight']
  fitbitWeightLogTimes = [log['logId'] / 1000 for log in fitbitWeightLogs]

  minLogNs = nano(min(fitbitWeightLogTimes))
  maxLogNs = nano(max(fitbitWeightLogTimes))

  googleWeightLogs = [FitbitWeightToGoogleWeight(log)
                        for log in fitbitWeightLogs]

  googleClient = GetGoogleClient()

  dataSource = dict(
    type='raw',
    application=dict(name='fitsync'),
    dataType=dict(
      name='com.google.weight',
      field=[dict(format='floatPoint', name='weight')]
    ),
    device=dict(
      type='scale',
      manufacturer='unknown',
      model='unknown',
      uid=scale['id'],
      version=scale['deviceVersion'],
    )
  )

  dataSourceId = GetDataSourceId(dataSource)

  # Ensure datasource exists for the device.
  try:
    googleClient.users().dataSources().get(
      userId='me',
      dataSourceId=dataSourceId)
  except HttpError, error:
    if not 'DataSourceId not found' in str(error):
      raise error
    # Doesn't exist, so create it.
    googleClient.users().dataSources().create(
      userId='me',
      body=dataSource)

  datasetId = '%s-%s' % (minLogNs, maxLogNs)

  def GetData():
    return googleClient.users().dataSources().datasets().get(
      userId='me',
      dataSourceId=dataSourceId,
      datasetId=datasetId).execute()

  def PointsDifference(left, right):
    return len(
      set(point['startTimeNanos'] for point in left['point']) -
      set(point['startTimeNanos'] for point in right['point']))

  command = 'patch'
  if len(sys.argv) > 1:
    command = sys.argv[1]

  # Get weight dataset.
  if command == 'get':
    data = GetData()
    for point in data['point']:
      startTimeNanos = point['startTimeNanos']
      fpVal = point['value'][0]['fpVal']
      startTimeSecs = int(startTimeNanos) / 1e9
      readableTime = time.strftime(TIME_FORMAT, time.localtime(startTimeSecs))
      weightLbs = float(fpVal) * POUNDS_PER_KILOGRAM
      print "%.1f lbs, %s" % (weightLbs, readableTime)

  # Delete weight dataset.
  elif command == 'delete':
    dataPrior = GetData()
    googleClient.users().dataSources().datasets().delete(
      userId='me',
      dataSourceId=dataSourceId,
      datasetId=datasetId).execute()
    dataPost = GetData()
    print "Deleted %d points" % PointsDifference(dataPrior, dataPost)

  # Upload weight dataset.  
  elif command == 'patch':
    dataPrior = GetData()
    googleClient.users().dataSources().datasets().patch(
      userId='me',
      dataSourceId=dataSourceId,
      datasetId=datasetId,
      body=dict(
        dataSourceId=dataSourceId,
        maxEndTimeNs=maxLogNs,
        minStartTimeNs=minLogNs,
        point=googleWeightLogs,
      )).execute()
    dataPost = GetData()
    print "Added %d points" % PointsDifference(dataPost, dataPrior)

  else:
    print "bad command"


def PointInData(startTimeNanos, data):
  if 'point' in data:
    for point in data['point']:
      if startTimeNanos == point['startTimeNanos']:
        return True


if __name__ == '__main__':
  main()
