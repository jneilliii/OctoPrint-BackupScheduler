# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
from . import schedule
import requests
from datetime import datetime
from octoprint.util import RepeatedTimer


class BackupschedulerPlugin(octoprint.plugin.SettingsPlugin,
							octoprint.plugin.AssetPlugin,
							octoprint.plugin.TemplatePlugin,
							octoprint.plugin.EventHandlerPlugin):

	def __init__(self):
		self._repeatedtimer = None
		self.backup_pending = False

	##~~ SettingsPlugin mixin

	def get_settings_defaults(self):
		return dict(
			installed_version=self._plugin_version,
			exclude_uploads=False,
			exclude_timelapse=False,
			backup_time="",
			backup_daily=False,
			backup_weekly=False,
			backup_weekly_day=7,
			backup_monthly=False,
			backup_monthly_day=1,
			backup_timelapses=False,
			backup_uploads=False
		)

	##~~ EventHandlerPlugin mixin

	def on_event(self, event, payload):
		if event in ("Startup", "SettingsUpdated") and self._settings.get_boolean(
				["backup_daily"]) or self._settings.get_boolean(["backup_weekly"]) or self._settings.get_boolean(
				["backup_monthly"]):
			self._logger.info("Clearing scheduled jobs.")
			schedule.clear("backupscheduler")
			if self._settings.get(["backup_time"]) != "":
				self._logger.info("Scheduling backup for %s." % self._settings.get(["backup_time"]))
				schedule.every().day.at(self._settings.get(["backup_time"])).do(self._perform_backup).tag(
					"backupscheduler")
				if not self._repeatedtimer:
					self._repeatedtimer = RepeatedTimer(60, schedule.run_pending)
					self._repeatedtimer.start()
		if event in ("PrintFailed", "PrintDone", "PrintCancelled") and self.backup_pending is True:
			self._logger.info("Starting backup after print completion.")
			self._perform_backup()

	def _perform_backup(self):
		if self._printer.is_printing():
			self._logger.info("Skipping backup for now because a print is ongoing")
			self.backup_pending = True
			return
		if datetime.now().day == self._settings.get_int(["backup_monthly_day"]) and self._settings.get_boolean(
				["backup_monthly"]) or datetime.now().isoweekday() == self._settings.get_int(
				["backup_weekly_day"]) and self._settings.get_boolean(["backup_weekly"]) or self._settings.get_boolean(
				["backup_daily"]):
			post_url = "http://127.0.0.1:{}/plugin/backup/backup".format(self._settings.global_get(["server", "port"]))
			exclusions = []
			if self._settings.get_boolean(["exclude_uploads"]):
				exclusions.append("uploads")
			if self._settings.get_boolean(["exclude_timelapse"]):
				exclusions.append("timelapse")
			self._logger.info("Performing scheduled backup with exclusions: {}.".format(exclusions))
			response = requests.post(post_url, json={"exclude": exclusions},
									 headers={"X-Api-Key": self._settings.global_get(["api", "key"])})
			self._logger.info(response.text)
		self.backup_pending = False

	##~~ AssetPlugin mixin

	def get_assets(self):
		return dict(
			js=["js/backupscheduler.js"]
		)

	##~~ Softwareupdate hook

	def get_update_information(self):
		return dict(
			backupscheduler=dict(
				displayName="Backup Scheduler",
				displayVersion=self._plugin_version,

				# version check: github repository
				type="github_release",
				user="jneilliii",
				repo="OctoPrint-BackupScheduler",
				current=self._plugin_version,

				# update method: pip
				pip="https://github.com/jneilliii/OctoPrint-BackupScheduler/archive/{target_version}.zip"
			)
		)


__plugin_name__ = "Backup Scheduler"
__plugin_pythoncompat__ = ">=2.7,<4"


def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = BackupschedulerPlugin()

	global __plugin_hooks__
	__plugin_hooks__ = {
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
	}
