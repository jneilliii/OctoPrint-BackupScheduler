/*
 * View model for Backup Scheduler
 *
 * Author: jneilliii
 * License: MIT
 */
$(function () {
    function BackupschedulerViewModel(parameters) {
        var self = this;

        self.settingsViewModel = parameters[0];
        self.sendTestEmailRunning = ko.observable(false);
        self.sendTestEmailSuccess = ko.observable(false);

        // Hack to remove automatically added Cancel button
		// See https://github.com/sciactive/pnotify/issues/141
		PNotify.prototype.options.confirm.buttons = [];

        //send retained notification
        self.onStartupComplete = function () {
            if (self.settingsViewModel.settings.plugins.backupscheduler.notification.retained_message.notifyMessage() != "") {
                var payload = ko.toJS(self.settingsViewModel.settings.plugins.backupscheduler.notification.retained_message);
                self.onDataUpdaterPluginMessage("backupscheduler", payload);
            }
        };

        self.onSettingsBeforeSave = function () {
            if (!self.settingsViewModel.settings.plugins.backupscheduler.daily.time().match(/([01]?[0-9]|2[0-3]):[0-5][0-9]/)) {
                self.settingsViewModel.settings.plugins.backupscheduler.daily.time('00:00');
            }
            if (!self.settingsViewModel.settings.plugins.backupscheduler.weekly.time().match(/([01]?[0-9]|2[0-3]):[0-5][0-9]/)) {
                self.settingsViewModel.settings.plugins.backupscheduler.weekly.time('00:00');
            }
            if (!self.settingsViewModel.settings.plugins.backupscheduler.monthly.time().match(/([01]?[0-9]|2[0-3]):[0-5][0-9]/)) {
                self.settingsViewModel.settings.plugins.backupscheduler.monthly.time('00:00');
            }
        };

        // receive data from server
        self.onDataUpdaterPluginMessage = function (plugin, data) {
            // exit early if not from this plugin
            if (plugin !== "backupscheduler") {
                return;
            }

            // Close any open notifications
            if(data.clear_notification && typeof self.notification_popup !== "undefined") {
                self.notification_popup.remove();
                self.notification_popup = undefined;
            }

            // NotificationMessages

            if (data.notifyType) {
                var notfiyType = data.notifyType;
                var notifyMessage = "\n" + data.notifyTitle + ":\n" + data.notifyMessage;
                var notifyHide = data.notifyHide;
                self.notification_popup = new PNotify({
                    title: "Backup Scheduler",
                    text: notifyMessage,
                    type: notfiyType,
                    hide: notifyHide,
                    confirm: {
                        confirm: true,
                        buttons: [{
                            text: gettext('Clear Error'),
                            addClass: 'btn-danger',
                            promptTrigger: true,
                            click: function(notice, value){
                                notice.remove();
                                notice.get().trigger("pnotify.cancel", [notice, value]);
                            }
                        }]
                    },
                    buttons: {
                        closer: false,
                        sticker: false,
                    },
                    history: {
                        history: false
                    }
                });
                self.notification_popup.get().on('pnotify.cancel', function() {self.resetRetainedNotifyMessageID();});
            }
        };

        // Send an Email to test settings
        self.sendTestEmail = function () {
            self.sendTestEmailRunning(true);
            let payload = {"smtp_server": self.settingsViewModel.settings.plugins.backupscheduler.send_email.smtp_server(),
                           "smtp_port": self.settingsViewModel.settings.plugins.backupscheduler.send_email.smtp_port(),
                           "smtp_tls": self.settingsViewModel.settings.plugins.backupscheduler.send_email.smtp_tls(),
                           "smtp_user": self.settingsViewModel.settings.plugins.backupscheduler.send_email.smtp_user(),
                           "smtp_password": self.settingsViewModel.settings.plugins.backupscheduler.send_email.smtp_password(),
                           "smtp_sender": self.settingsViewModel.settings.plugins.backupscheduler.send_email.sender(),
                           "smtp_recipient": self.settingsViewModel.settings.plugins.backupscheduler.send_email.recipient()}
            OctoPrint.simpleApiCommand("backupscheduler", "sendTestEmail", payload).done(function (data) {
                self.sendTestEmailSuccess(data.success)
                self.sendTestEmailRunning(false);
                setTimeout(self.sendTestEmailSuccess, 10000, false)
            }).fail(function (data) {
                self.sendTestEmailRunning(false);
            });
        };

        self.resetRetainedNotifyMessageID = function () {
            OctoPrint.simpleApiCommand("backupscheduler", "clearRetainedMessage", {}).done(function (data) {
                if (data.success) {
                    self.settingsViewModel.settings.plugins.backupscheduler.notification.retained_message = {};
                }
            });
        };
    }

    OCTOPRINT_VIEWMODELS.push({
        construct: BackupschedulerViewModel,
        // ViewModels your plugin depends on, e.g. loginStateViewModel, settingsViewModel, ...
        dependencies: ["settingsViewModel"],
        elements: ["#settings_plugin_backupscheduler"]
    });
});
