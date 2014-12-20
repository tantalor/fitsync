Fitsync is a python app that syncs data between Fitbit and Google Fit.

Currently, it only copies weight data from Fitbit to Google.

## Setup

### Environment

Use `virtualenv` to create an environment to install required packages,

		$ virtualenv env

Activate the environment in your shell,

		$ source env/bin/activate

Use `pip` to install the required packages,

		$ pip install -r requirements.txt

## Usage

Run `fitsync.py` to download data from Fitbit and upload to Google,

		$ python fitsync.py

Use the `delete` command to remove data from Google,

		$ python fitsync.py delete

Use the `get` command to see the data stored in Google,

		$ python fitsync.py get

## See your data

To view weight data on [Google Fit](https://fit.google.com),

1. Choose "See graph details" for any day
2. Choose "+ Add chart" 
3. Choose "Weight"
4. Choose "Day", "Week", or "Month" to see the data for that time period
