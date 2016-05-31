#!/usr/bin/env python

import httplib2
import sys
import time
import yaml
import argparse
import logging
import datetime
import dateutil.tz
import dateutil.parser

import fitbit
from apiclient.discovery import build
from oauth2client.file import Storage
from oauth2client.client import OAuth2Credentials
from googleapiclient.errors import HttpError


POUNDS_PER_KILOGRAM = 2.20462

TIME_FORMAT = "%a, %d %b %Y %H:%M:%S"


def GetGoogleClient(filename):
  logging.debug("Creating Google client")
  credentials = Storage(filename).get()
  http = credentials.authorize(httplib2.Http())
  client = build('fitness', 'v1', http=http)
  logging.debug("Google client created")
  return client


dawnOfTime = datetime.datetime(1970, 1, 1, tzinfo=dateutil.tz.tzutc())

def epochOfFitbitLog(logEntry, tzinfo):
  logTimestamp = "{} {}".format(logEntry["date"], logEntry["time"])
  logTime = dateutil.parser.parse(logTimestamp).replace(tzinfo=tzinfo)
  return (logTime - dawnOfTime).total_seconds()

def nano(val):
  """Converts a number to nano (str)."""
  return '%d' % (val * 1e9)


def FitbitWeightToGoogleWeight(fitbitWeightLog, tzinfo):
  logSecs = epochOfFitbitLog(fitbitWeightLog, tzinfo)

  logWeightLbs = fitbitWeightLog['weight']
  logWeightKg = logWeightLbs / POUNDS_PER_KILOGRAM
  return dict(
    dataTypeName='com.google.weight',
    endTimeNanos=nano(logSecs),
    startTimeNanos=nano(logSecs),
    value=[dict(fpVal=logWeightKg)],
  )

def GetBodyweight(filename):
  logging.debug("Creating Fitbit client")
  credentials = yaml.load(open(filename))
  client = fitbit.Fitbit(**credentials)
  logging.debug("Fitbit client created")

  try:
    logging.debug("Getting Fitbit data")
    userProfile = client.user_profile_get()
    tzinfo = dateutil.tz.gettz(userProfile['user']['timezone'])

    devices = client.get_devices()
    (scale,) = (device for device in devices if device['type'] == 'SCALE')

    fitbitBodyweight = client.get_bodyweight(period='1m')
    fitbitWeightLogs = fitbitBodyweight['weight']
    fitbitWeightLogTimes = [epochOfFitbitLog(log, tzinfo) for log in fitbitWeightLogs]

    minLogNs = nano(min(fitbitWeightLogTimes))
    maxLogNs = nano(max(fitbitWeightLogTimes))

    googleWeightLogs = [FitbitWeightToGoogleWeight(log, tzinfo)
                          for log in fitbitWeightLogs]
    logging.debug("Got Fitbit data")
  finally:
    dump = False
    for t in ('access_token', 'refresh_token'):
      if client.client.token[t] != credentials[t]:
        credentials[t] = client.client.token[t]
        dump = True
    if dump:
      logging.debug("Updating Fitbit credentials")
      yaml.dump(credentials, open(filename, 'w'))

  return googleWeightLogs, minLogNs, maxLogNs, scale

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
  parser = argparse.ArgumentParser("Transfer Fitbit weight data to Google Fit")
  parser.add_argument("command", choices=('patch', 'get', 'delete'), help="What to do")
  parser.add_argument("-d", "--debug", action="count", default=0, help="Increase debugging level")
  parser.add_argument("-g", "--google-creds", default="google.json", help="Google credentials file")
  parser.add_argument("-f", "--fitbit-creds", default="fitbit.yaml", help="Fitbit credentials file")
  args = parser.parse_args()

  debugLevel = logging.WARNING - (args.debug * 10)
  logging.basicConfig(level=max(debugLevel, 0))
  logging.root.name = "fitsync"

  googleWeightLogs, minLogNs, maxLogNs, scale = GetBodyweight(args.fitbit_creds)

  googleClient = GetGoogleClient(args.google_creds)

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
      dataSourceId=dataSourceId).execute()
  except HttpError, error:
    if not 'DataSourceId not found' in str(error):
      raise error
    # Doesn't exist, so create it.
    googleClient.users().dataSources().create(
      userId='me',
      body=dataSource).execute()

  datasetId = '%s-%s' % (minLogNs, maxLogNs)

  def GetData():
    ret = googleClient.users().dataSources().datasets().get(
      userId='me',
      dataSourceId=dataSourceId,
      datasetId=datasetId).execute()
    #insert empty 'point' when there is nothing
    if 'point' not in ret:
      ret['point']=[]
    return ret

  def PointsDifference(left, right):
    return len(
      set(point['startTimeNanos'] for point in left['point']) -
      set(point['startTimeNanos'] for point in right['point']))

  # Get weight dataset.
  if args.command == 'get':
    data = GetData()
    numpoints = 0
    for point in data['point']:
      startTimeNanos = point['startTimeNanos']
      fpVal = point['value'][0]['fpVal']
      startTimeSecs = int(startTimeNanos) / 1e9
      readableTime = time.strftime(TIME_FORMAT, time.localtime(startTimeSecs))
      weightKgs = float(fpVal)
      weightLbs = float(fpVal) * POUNDS_PER_KILOGRAM
      print("%.1f lbs ( %.2f kgs ), %s" % (weightLbs, weightKgs, readableTime))
      numpoints += 1
    print("Total %d points (in Google Fit)" % numpoints)

  # Delete weight dataset.
  elif args.command == 'delete':
    dataPrior = GetData()
    googleClient.users().dataSources().datasets().delete(
      userId='me',
      dataSourceId=dataSourceId,
      datasetId=datasetId).execute()
    dataPost = GetData()
    print("Deleted %d points (from Google Fit)" % PointsDifference(dataPrior, dataPost))

  # Upload weight dataset.  
  elif args.command == 'patch':
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
    print("Added %d points (to Google Fit)" % PointsDifference(dataPost, dataPrior))



def PointInData(startTimeNanos, data):
  if 'point' in data:
    for point in data['point']:
      if startTimeNanos == point['startTimeNanos']:
        return True


if __name__ == '__main__':
  main()

