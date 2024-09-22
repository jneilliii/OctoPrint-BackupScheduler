# coding=utf-8
from __future__ import absolute_import

import logging

import octoprint.plugin
from . import schedule
import threading
from datetime import datetime
from octoprint.util import RepeatedTimer, version
import os
import smtplib
from smtplib import *
from email.mime.text import MIMEText
from flask_babel import gettext

class BackupschedulerPlugin(octoprint.plugin.SettingsPlugin,
							octoprint.plugin.AssetPlugin,
							octoprint.plugin.TemplatePlugin,
							octoprint.plugin.EventHandlerPlugin,
							octoprint.plugin.SimpleApiPlugin,
							octoprint.plugin.StartupPlugin):

	def __init__(self):
		self._repeatedtimer = None
		self.backup_pending = False
		self.backup_pending_type = []
		self.current_settings = None
		self.backup_helpers = None
		self._smtp_password = None

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
			startup_backups=[],
			check_mount=False,
   			send_email={"enabled": False, "send_successful": False, "smtp_server": "", "smtp_port": 25, "smtp_tls": False, "smtp_user": "", "sender": "", "receiver": ""},
			notification={"enabled": True, "retainedNotifyMessageID": ""}
		)

	# blacklist SMTP settings for REST API
	def get_settings_restricted_paths(self):
		from octoprint.access.permissions import Permissions
		return {'admin':[["send_email"]]}

	def on_settings_save(self, data):
		if "send_email" in data:
			if "smtp_password" in data["send_email"]:
				os.environ["BACKUPSCHEDULER_SMTP_PASSWORD"] = data["send_email"]["smtp_password"]
				del data["send_email"]["smtp_password"]
				if len(data["send_email"]) == 0:
					del data["send_email"]
		octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
		return data

	def on_settings_load(self):
		data = octoprint.plugin.SettingsPlugin.on_settings_load(self)
		if os.environ.get("BACKUPSCHEDULER_SMTP_PASSWORD"):
			data["send_email"]["smtp_password"] = os.environ.get("BACKUPSCHEDULER_SMTP_PASSWORD")
		return data

	def on_plugin_pending_uninstall(self):
		os.environ.pop("BACKUPSCHEDULER_SMTP_PASSWORD", None)


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
		self._smtp_password = os.environ.get("BACKUPSCHEDULER_SMTP_PASSWORD")


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
		if self._settings.get_boolean(["check_mount"]):
			backup_folder = os.path.join(self._settings.getBaseFolder("data"), "backup")
			if not os.path.ismount(backup_folder):
				self._logger.debug("Skipping {} because there is no mount.".format(backup_type))
				self._sendNotificationToClient("no_mount", True)
				if self._settings.get_boolean(["send_email", "enabled"]):
					body = self._loadFileWithPlaceholders("no_mount.html", {"backup_folder": backup_folder})
					self._sendEmailNotification("OctoPrint Backup failed: Mount was missing!", body)
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
		backup_filename = "{}-{}-{:%Y%m%d-%H%M%S}.zip".format(instance_name, backup_type.replace("_backups", ""), datetime.now())
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


	# ~~ BackupPlugin hooks

	#TODO: Trigger abort in OctoPrint backup plugin in general to avoid SD writes - actually not possible by OctoPrint
	# def before_backup(self):
	# 	settings = octoprint.plugin.plugin_settings_for_settings_plugin(
	# 		"backup", self
	# 	)
	# 	datafolder = os.path.join(settings.getBaseFolder("data"), "backup")
	# 	if self._settings.get_boolean("check_mount"):
	# 		if not os.path.ismount(datafolder):
	# 			#create error message
	# 			return

	def after_backup(self, error):
		if error:
			self._sendNotificationToClient("backup_failed", True)
			if self._settings.get_boolean(["send_email", "enabled"]):
				#TODO noch ein paar mehr Infos einbauen
				self._settings.get_plugin_data_folder()
				body = self._loadFileWithPlaceholders("backup_failed.html")
				self._sendEmailNotification("OctoPrint Backup failed", body)
		elif self._settings.get_boolean(["send_email", "send_successful"]):
			body = self._loadFileWithPlaceholders("backup_successful.html")
			self._sendEmailNotification("OctoPrint Backup successful", body)
			self._settings.set(["send_email", "retainedNotifyMessageID"], "")


	# ~~ Client notifications

	# sends the data-dictonary to the client/browser
	def _sendDataToClient(self, eventID, dataDict = dict()):
		dataDict["eventID"] = eventID
		self._plugin_manager.send_plugin_message(self._identifier, dataDict)

	#send notification to client/browser
	def _sendNotificationToClient(self, notifyMessageID, retain = False):
		self._logger.debug("Plugin message: {}".format(notifyMessageID))
		if retain:
			self._settings.set(["notification", "retainedNotifyMessageID"], notifyMessageID)
			self._settings.save()
		self._plugin_manager.send_plugin_message(self._identifier, dict(notifyMessageID=notifyMessageID))

	# Load html-template files for mails - {{placeholder}} format for replacement
	def _loadFileWithPlaceholders(self, filename, placeholders = dict()):
		returnText = ""
		file = os.path.join(self._basefolder, "static", "mailtmpl", filename)
		with open(file, 'r', encoding='utf-8') as f:
			for row in f:
				returnText += row
			for key, value in placeholders.items():
				returnText = returnText.replace("{{" + key + "}}", value)
		return returnText

	def _sendEmailNotification(self, subject, body):
		msg = MIMEText(body, "html")
		msg['Subject'] = subject
		msg['From'] = self._settings.get(["send_email", "sender"])
		msg['To'] = self._settings.get(["send_email", "receiver"])
		# Send the message via an SMTP server
		try:
			if self._settings.get_boolean(["send_email", "smtp_tls"]):
				server =  smtplib.SMTP_SSL()
			else:
				server =  smtplib.SMTP()
			server.connect(self._settings.get(["send_email", "smtp_server"]), self._settings.get_int(["send_email", "smtp_port"]))
			server.ehlo()
			if self._settings.get(["send_email", "smtp_user"]) != "" and self._smtp_password is not None:
				server.login(self._settings.get(["send_email", "smtp_user"]), self._smtp_password)
			try:
				server.sendmail(msg['From'], msg['To'], msg.as_string())
			finally:
				server.quit()
		except SMTPResponseException as e:
			error_code = str(e.smtp_code)
			error_message = e.smtp_error
			self._logger.error(error_code + " - " + error_message)
			data = {}
			data["notifyTitel"] = gettext("SMTP Error")
			data["notifyText"] = str(error_code) + " - " + error_message
			data["notifyType"] = "error"
			data["notifyHide"] = False
			self._sendDataToClient("smtp_error", data)
		except ConnectionError as e:
			error_code = str(e.errno)
			error_message = e.strerror
			self._logger.error(error_code + " - " + error_message)
			data = {}
			data["notifyTitel"] = gettext("SMTP Error")
			data["notifyText"] = str(error_code) + " - " + error_message
			data["notifyType"] = "error"
			data["notifyHide"] = False
			self._sendDataToClient("smtp_error", data)

	def get_api_commands(self):
		return {'sendTestEmail': []}

	def on_api_command(self, command, data):
		import flask
		from octoprint.server import user_permission
		if not user_permission.can():
			return flask.make_response("Insufficient rights", 403)

		if command == "sendTestEmail":
			self._logger.debug("Send an Email to test settings.")
			self._sendEmailNotification("OctoPrint Backup: Testmessage", "OctoPrint Backup: Testmessage")
			# return flask.jsonify(results)


	# ~~ AssetPlugin mixin

	def get_assets(self):
		return dict(
			js=["js/backupscheduler.js"]
		)

	# ~~ Softwareupdate hook

	def get_update_information(self):
		data = dict(
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

		# if octoprint version is less than 1.9.0, lock update check to specific branch
		if not version.is_octoprint_compatible(">=1.6.0"):
			data['type'] = 'github_commit'
			data['branch'] = '0.0.6'

		return dict(backupscheduler=data)


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
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
  		"octoprint.plugin.backup.after_backup": __plugin_implementation__.after_backup
	}
