from rms.analytics.runner import execute as run_report


def execute(filters=None):
	return run_report('fulfillment', filters)
