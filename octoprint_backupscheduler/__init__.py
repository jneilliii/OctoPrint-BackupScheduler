# coding=utf-8
from __future__ import absolute_import

import logging

import octoprint.plugin
from . import schedule
import threading
from datetime import datetime
from octoprint.util import RepeatedTimer


class BackupschedulerPlugin(octoprint.plugin.SettingsPlugin,
							octoprint.plugin.AssetPlugin,
							octoprint.plugin.TemplatePlugin,
							octoprint.plugin.EventHandlerPlugin,
							octoprint.plugin.StartupPlugin):

	def __init__(self):
		self._repeatedtimer = None
		self.backup_pending = False
		self.backup_pending_type = []
		self.current_settings = None
		self.backup_helpers = None

	# ~~ SettingsPlugin mixin

	def get_settings_defaults(self):
		return dict(
			installed_version=self._plugin_version,
			daily={"enabled": False, "time": "00:00", "retention": 1, "exclude_uploads": False, "exclude_timelapse": False},
			daily_backups=[],
			weekly={"enabled": False, "time": "00:00", "day": 7, "retention": 1, "exclude_uploads": False,
					"exclude_timelapse": False},
			weekly_backups=[],
			monthly={"enabled": False, "time": "00:00", "day": 1, "retention": 1, "exclude_uploads": False,
					 "exclude_timelapse": False},
			monthly_backups=[],
			startup={"enabled": False, "retention": 1, "exclude_uploads": False, "exclude_timelapse": False},
			startup_backups=[]
		)

	# ~~ StartupPlugin mixin

	def on_after_startup(self):
		# can this be moved to plugin_load or init to prevent additional processing?
		self.backup_helpers = self._plugin_manager.get_helpers("backup", "create_backup", "delete_backup")
		if "create_backup" not in self.backup_helpers or "delete_backup" not in self.backup_helpers:
			self._logger.info("Missing backup helpers, aborting.")
			return
		if self._settings.get_boolean(["startup", "enabled"]):
			t = threading.Timer(1, self._perform_backup, kwargs={"backup_type": "startup_backups"})
			t.daemon = True
			t.start()

	# ~~ EventHandlerPlugin mixin

	def on_event(self, event, payload):
		if event not in ("Startup", "SettingsUpdated", "PrintFailed", "PrintDone"):
			return
		if self._settings.get_boolean(["daily", "enabled"]) or self._settings.get_boolean(
				["weekly", "enabled"]) or self._settings.get_boolean(["monthly", "enabled"]):
			if event == "Startup":
				self.current_settings = {"daily": self._settings.get(["daily"]),
										 "weekly": self._settings.get(["weekly"]),
										 "monthly": self._settings.get(["monthly"])}
				backups_enabled = False
				self._logger.debug("Clearing scheduled jobs.")
				schedule.clear("backupscheduler")
				if self._settings.get_boolean(["daily", "enabled"]) and self._settings.get(["daily", "time"]) != "":
					backups_enabled = True
					self._logger.debug("Scheduling daily backup for %s." % self._settings.get(["daily", "time"]))
					schedule.every().day.at(self._settings.get(["daily", "time"])).do(self._perform_backup,
																					  backup_type="daily_backups").tag(
						"backupscheduler")
				if self._settings.get_boolean(["weekly", "enabled"]) and self._settings.get(["weekly", "time"]) != "":
					backups_enabled = True
					self._logger.debug("Scheduling weekly backup for %s." % self._settings.get(["weekly", "time"]))
					schedule.every().day.at(self._settings.get(["weekly", "time"])).do(self._perform_backup,
																					   backup_type="weekly_backups").tag(
						"backupscheduler")
				if self._settings.get_boolean(["monthly", "enabled"]) and self._settings.get(["monthly", "time"]) != "":
					backups_enabled = True
					self._logger.debug("Scheduling monthly backup for %s." % self._settings.get(["monthly", "time"]))
					schedule.every().day.at(self._settings.get(["monthly", "time"])).do(self._perform_backup,
																						backup_type="monthly_backups").tag(
						"backupscheduler")
				if not self._repeatedtimer and backups_enabled is True:
					self._repeatedtimer = RepeatedTimer(60, schedule.run_pending)
					self._repeatedtimer.start()
			if event == "SettingsUpdated":
				if self.current_settings != {"daily": self._settings.get(["daily"]),
											 "weekly": self._settings.get(["weekly"]),
											 "monthly": self._settings.get(["monthly"])}:
					self._logger.debug("Settings updated.")
					self.on_event("Startup", {})
			if event in ("PrintFailed", "PrintDone") and self.backup_pending is True:
				for backup in self.backup_pending_type:
					self._logger.debug("Starting {} after print completion.".format(backup))
					self._perform_backup(backup_type=backup)

	def _perform_backup(self, backup_type=None):
		if self._printer.is_printing():
			self._logger.debug("Skipping {} for now because a print is ongoing.".format(backup_type))
			self.backup_pending = True
			if backup_type != "all" and backup_type not in self.backup_pending_type:
				self.backup_pending_type.append(backup_type)
			return
		exclusions = []
		retention = 0
		if backup_type == "monthly_backups":
			if datetime.now().day == self._settings.get_int(["monthly", "day"]) and self._settings.get_boolean(
					["monthly", "enabled"]):
				if self._settings.get_boolean(["monthly", "exclude_uploads"]):
					exclusions.append("uploads")
				if self._settings.get_boolean(["monthly", "exclude_timelapse"]):
					exclusions.append("timelapse")
				retention = self._settings.get_int(["monthly", "retention"])
				if "monthly_backups" in self.backup_pending_type:
					self.backup_pending_type.remove("monthly_backups")
			else:
				return
		if backup_type == "weekly_backups":
			if datetime.now().isoweekday() == self._settings.get_int(["weekly", "day"]) and self._settings.get_boolean(
					["weekly", "enabled"]):
				if self._settings.get_boolean(["weekly", "exclude_uploads"]):
					exclusions.append("uploads")
				if self._settings.get_boolean(["weekly", "exclude_timelapse"]):
					exclusions.append("timelapse")
				retention = self._settings.get_int(["weekly", "retention"])
				if "weekly_backups" in self.backup_pending_type:
					self.backup_pending_type.remove("weekly_backups")
			else:
				return
		if backup_type == "daily_backups":
			if self._settings.get_boolean(["daily", "enabled"]):
				if self._settings.get_boolean(["daily", "exclude_uploads"]):
					exclusions.append("uploads")
				if self._settings.get_boolean(["daily", "exclude_timelapse"]):
					exclusions.append("timelapse")
				retention = self._settings.get_int(["daily", "retention"])
				if "daily_backups" in self.backup_pending_type:
					self.backup_pending_type.remove("daily_backups")
			else:
				return
		if backup_type == "startup_backups":
			if self._settings.get_boolean(["startup", "enabled"]):
				if self._settings.get_boolean(["startup", "exclude_uploads"]):
					exclusions.append("uploads")
				if self._settings.get_boolean(["startup", "exclude_timelapse"]):
					exclusions.append("timelapse")
				retention = self._settings.get_int(["startup", "retention"])
				if "startup_backups" in self.backup_pending_type:
					self.backup_pending_type.remove("startup_backups")
			else:
				return

		instance_name = self._settings.global_get(["appearance", "name"]) or "octoprint"
		backup_filename = "{}-{}-{:%Y%m%d%H%M%S}.zip".format(instance_name, backup_type.replace("_backups", ""), datetime.now())
		self._logger.debug("Performing {} with exclusions: {} as {}.".format(backup_type, exclusions, backup_filename))
		self.backup_helpers["create_backup"](exclude=exclusions, filename=backup_filename)
		completed_backups = self._settings.get([backup_type])
		completed_backups.append(backup_filename)
		# do retention check here and delete older backups
		delete_backups = completed_backups[:-retention]
		self._logger.debug("Deleting backups: {}".format(delete_backups))
		for backup in delete_backups:
			self.backup_helpers["delete_backup"](backup)
		retained_backups = completed_backups[-retention:]
		self._settings.set([backup_type], retained_backups)
		self._settings.save(trigger_event=False)
		self._logger.debug(self._settings.get([backup_type]))
		self.backup_pending = False

	# ~~ AssetPlugin mixin

	def get_assets(self):
		return dict(
			js=["js/backupscheduler.js"]
		)

	# ~~ Softwareupdate hook

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
				stable_branch=dict(
					name="Stable", branch="master", comittish=["master"]
				),
				prerelease_branches=[
					dict(
						name="Release Candidate",
						branch="rc",
						comittish=["rc", "master"],
					)
				],
				# update method: pip
				pip="https://github.com/jneilliii/OctoPrint-BackupScheduler/archive/{target_version}.zip"
			)
		)


__plugin_name__ = "Backup Scheduler"
__plugin_pythoncompat__ = ">=2.7,<4"

def __plugin_check__():
	from octoprint.util.version import is_octoprint_compatible
	compatible = is_octoprint_compatible(">=1.6.0")
	if not compatible:
		logging.getLogger(__name__).info("Backup Scheduler requires OctoPrint 1.6.0+")
	return compatible

def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = BackupschedulerPlugin()

	global __plugin_hooks__
	__plugin_hooks__ = {
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
	}
