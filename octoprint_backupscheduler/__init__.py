# coding=utf-8
from __future__ import absolute_import

import logging
import octoprint.plugin
from . import schedule
import threading
from datetime import datetime
from octoprint.util import RepeatedTimer, version, to_bytes, to_str
import os
import smtplib
from email.mime.text import MIMEText
from flask_babel import gettext
from cryptography.fernet import Fernet
import base64

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
            send_email={"enabled": False, "send_successful": False, "smtp_server": "", "smtp_port": 25, "smtp_tls": False, "smtp_user": "", "sender": "", "recipient": ""},
            notification={"enabled": True, "retained_message": {}}
        )

    # blacklist SMTP settings for REST API
    def get_settings_restricted_paths(self):
        return {'admin':[["send_email"]]}

    def on_settings_save(self, data):
        if "send_email" in data:
            if "smtp_password" in data["send_email"]:
                f = Fernet(base64.urlsafe_b64encode(to_bytes(self._settings.global_get(["server", "secretKey"]))))
                data_filename = os.path.join(self.get_plugin_data_folder(), ".data.txt")
                with open(data_filename, "wb") as data_file:
                    data_file.write(f.encrypt(to_bytes(data["send_email"]["smtp_password"])))
                del data["send_email"]["smtp_password"]
                if len(data["send_email"]) == 0:
                    del data["send_email"]
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        return data

    def _get_encrypted_password(self):
        data_filename = os.path.join(self.get_plugin_data_folder(), ".data.txt")
        if os.path.exists(data_filename):
            f = Fernet(base64.urlsafe_b64encode(to_bytes(self._settings.global_get(["server", "secretKey"]))))
            with open(data_filename, "rb") as data_file:
                return to_str(f.decrypt(data_file.read())).decode()
        return None

    def on_settings_load(self):
        data = octoprint.plugin.SettingsPlugin.on_settings_load(self)
        data["send_email"]["smtp_password"] = self._get_encrypted_password()
        return data


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
                    self._logger.debug(f"Starting {backup} after print completion.")
                    self._perform_backup(backup_type=backup)

    def _perform_backup(self, backup_type=None):
        if self._printer.is_printing():
            self._logger.debug(f"Skipping {backup_type} for now because a print is ongoing.")
            self.backup_pending = True
            if backup_type != "all" and backup_type not in self.backup_pending_type:
                self.backup_pending_type.append(backup_type)
            return
        if self._settings.get_boolean(["check_mount"]):
            backup_folder = os.path.join(self._settings.getBaseFolder("data"), "backup")
            if not os.path.ismount(backup_folder):
                self._logger.debug(f"Skipping {backup_type} because there is no mount.")
                data = {
                    "notifyTitle": gettext("Backup Failed"),
                    "notifyMessage": gettext("Last Backup failed because of a missing mount! Please check why the mount was missing. Reset retained flag to confirm notification."),
                    "notfiyType": "error",
                    "notifyHide": False
                }
                self._sendNotificationToClient(data, True)
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

    def additional_excludes_hook(self, excludes, *args, **kwargs):
        # don't include anything from plugin's data folder in backup
        return ["."]

    def after_backup(self, error):
        if error:
            data = {"notifyTitle": gettext("Backup Failed"),
                "notifyMessage": gettext("Something went wrong with the last backup. Please check octoprint.log for possible causes."),
                "notfiyType": "error", "notifyHide": False}
            self._sendNotificationToClient(data, True)
            if self._settings.get_boolean(["send_email", "enabled"]):
                body = self._loadFileWithPlaceholders("backup_failed.html")
                self._sendEmailNotification("OctoPrint Backup Failed", body)
        else:
            self._sendNotificationToClient({"notifyTitle": "", "clear_notification": True})
            self._settings.remove(["notification", "retained_message"])
            self._settings.save(trigger_event=True)
            if self._settings.get_boolean(["send_email", "send_successful"]):
                body = self._loadFileWithPlaceholders("backup_successful.html")
                self._sendEmailNotification("OctoPrint Backup Successful", body)

    # ~~ Client notifications

    # send notification to client/browser
    def _sendNotificationToClient(self, payload, retain = False):
        if payload["notifyTitle"] == gettext("SMTP Error"):
            # always send smtp error messages to GUI
            pass
        elif not self._settings.get_boolean(["notification", "enabled"]):
            return

        self._logger.debug(f"Plugin message: {payload}")
        if retain:
            # TODO: add timestamp and append to previous notification message?
            self._settings.set(["notification", "retained_message"], payload)
            self._settings.save(trigger_event=True)
        self._plugin_manager.send_plugin_message(self._identifier, payload)

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
        msg['To'] = self._settings.get(["send_email", "recipient"])
        # Send the message via an SMTP server
        try:
            if self._settings.get_boolean(["send_email", "smtp_tls"]):
                server =  smtplib.SMTP_SSL()
            else:
                server =  smtplib.SMTP()
            # set host manually to deal with python bug value error, see https://bugs.python.org/issue36094
            server._host = self._settings.get(["send_email", "smtp_server"])
            server.connect(self._settings.get(["send_email", "smtp_server"]), self._settings.get_int(["send_email", "smtp_port"]))
            server.ehlo()
            if self._settings.get(["send_email", "smtp_user"]) != "":
                server.login(self._settings.get(["send_email", "smtp_user"]), self._get_encrypted_password())
            try:
                server.sendmail(msg['From'], msg['To'], msg.as_string())
            finally:
                server.quit()
        except Exception as e:
            error_message = str(e)
            self._logger.error(error_message)
            data = {"notifyTitle": gettext("SMTP Error"), "notifyMessage": error_message, "notifyType": "error",
                    "notifyHide": False}
            self._sendNotificationToClient(data, True)

    def get_api_commands(self):
        return {'sendTestEmail': [], 'clearRetainedMessage': []}

    def on_api_command(self, command, data):
        import flask
        from octoprint.server import user_permission
        if not user_permission.can():
            return flask.make_response("Insufficient rights", 403)

        if command == "sendTestEmail":
            self._logger.debug("Send an Email to test settings.")
            self._sendEmailNotification("OctoPrint Backup: Test Message", "OctoPrint Backup: Test Message")
            # return flask.jsonify(results)
        if command == "clearRetainedMessage":
            self._logger.debug("Clearing retained message")
            self._settings.remove(["notification", "retained_message"])
            self._settings.save(trigger_event=True)
            return flask.jsonify({"success": True})

    # TemplatePlugin mixin

    def get_template_vars(self):
        return {"plugin_version": self._plugin_version}

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

        return dict(backupscheduler=data)


__plugin_name__ = "Backup Scheduler"
__plugin_pythoncompat__ = ">=2.7,<4"

def __plugin_check__():
    from octoprint.util.version import is_octoprint_compatible
    compatible = is_octoprint_compatible(">=1.9.0")
    if not compatible:
        logging.getLogger(__name__).info("Backup Scheduler requires OctoPrint 1.9.0+")
    return compatible

def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = BackupschedulerPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
        "octoprint.plugin.backup.after_backup": __plugin_implementation__.after_backup,
        "octoprint.plugin.backup.additional_excludes": __plugin_implementation__.additional_excludes_hook
    }
