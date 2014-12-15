import httplib2
import sys
from time import time as now
import yaml

import fitbit
from apiclient.discovery import build
from oauth2client.file import Storage
from oauth2client.client import OAuth2Credentials
from googleapiclient.errors import HttpError


POUNDS_PER_KILOGRAM = 2.20462


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

	command = 'patch'
	if len(sys.argv) > 1:
		command = sys.argv[1]

	# Get weight dataset.
	if command == 'get':
		print googleClient.users().dataSources().datasets().get(
			userId='me',
			dataSourceId=dataSourceId,
			datasetId=datasetId).execute()

	# Delete weight dataset.
	if command == 'delete':
		googleClient.users().dataSources().datasets().delete(
			userId='me',
			dataSourceId=dataSourceId,
			datasetId=datasetId).execute()
		print "deleted data"

	# Upload weight dataset.	
	if command == 'patch':
		print googleClient.users().dataSources().datasets().patch(
			userId='me',
			dataSourceId=dataSourceId,
			datasetId=datasetId,
			body=dict(
				dataSourceId=dataSourceId,
				maxEndTimeNs=maxLogNs,
				minStartTimeNs=minLogNs,
				point=googleWeightLogs,
			)).execute()


if __name__ == '__main__':
  main()
