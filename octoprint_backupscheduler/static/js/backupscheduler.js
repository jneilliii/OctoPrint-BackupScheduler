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

        //send retained notification
        self.onStartupComplete = function () {
            if (self.settingsViewModel.settings.plugins.backupscheduler.notification.retainedNotifyMessageID() !== "") {
                self.onDataUpdaterPluginMessage(plugin, { notifyMessageID: self.settingsViewModel.settings.plugins.backupscheduler.notification.retainedNotifyMessageID() })
            }
        }

        self.onSettingsBeforeSave = function () {
            if (!self.settingsViewModel.settings.plugins.backupscheduler.daily.time().match(/([01]?[0-9]|2[0-3]):[0-5][0-9]/)) {
                self.settingsViewModel.settings.plugins.backupscheduler.daily.time('00:00')
            }
            if (!self.settingsViewModel.settings.plugins.backupscheduler.weekly.time().match(/([01]?[0-9]|2[0-3]):[0-5][0-9]/)) {
                self.settingsViewModel.settings.plugins.backupscheduler.weekly.time('00:00')
            }
            if (!self.settingsViewModel.settings.plugins.backupscheduler.monthly.time().match(/([01]?[0-9]|2[0-3]):[0-5][0-9]/)) {
                self.settingsViewModel.settings.plugins.backupscheduler.monthly.time('00:00')
            }
        }

        // receive data from server
        self.onDataUpdaterPluginMessage = function (plugin, data) {
            // debugger
            // if (plugin == "backupscheduler") {
            // NotificationMessages
            if (data.notifyType) {
                var notfiyType = data.notifyType;
                var notifyTitle = data.notifyTitle;
                var notifyMessage = data.notifyMessage;
                var notifyHide = data.notifyHide;
                new PNotify({
                    title: notifyTitle,
                    text: notifyMessage,
                    type: notfiyType,
                    hide: notifyHide
                });
            }
            if (data.notifyMessageID) {
                switch (data.notifyMessageID) {
                    case "no_mount":
                        new PNotify({
                            title: gettext("Backup failed"),
                            text: gettext("Last Backup failed because of a missing mount! Please check why the mount was missing. Reset retained flag to confirm notification."),
                            type: "error",
                            hide: false
                        });
                        break;
                    case "backup_failed":
                        new PNotify({
                            title: gettext("Backup failed"),
                            text: gettext("Last Backup failed! Issues caused inside OctoPrint. Please check why the backup could not be created. Reset retained flag to confirm notification."),
                            type: "error",
                            hide: false
                        });
                        break;
                }
            }
            // }
        }

        // Send an Email to test settings
        self.sendTestEmail = function () {
            self.sendTestEmailRunning(true);
            $.ajax({
                url: API_BASEURL + "plugin/backupscheduler",
                type: "POST",
                dataType: "json",
                data: JSON.stringify({
                    command: "sendTestEmail"
                }),
                contentType: "application/json; charset=UTF-8"
            }).done(function (data) {
                for (key in data) {
                    // if(data[key].length){
                    // 	self.crawl_results.push({name: ko.observable(key), files: ko.observableArray(data[key])});
                    // }
                }

                console.log(data);
                // if(self.crawl_results().length === 0){
                // 	self.crawl_results.push({name: ko.observable('No convertible files found'), files: ko.observableArray([])});
                // }
                self.sendTestEmailRunning(false);
            }).fail(function (data) {
                self.sendTestEmailRunning(false);
            });
        };

        self.resetRetainedNotifyMessageID = function () {
            self.settingsViewModel.settings.plugins.backupscheduler.notification.retainedNotifyMessageID("");
        };
    }

    OCTOPRINT_VIEWMODELS.push({
        construct: BackupschedulerViewModel,
        // ViewModels your plugin depends on, e.g. loginStateViewModel, settingsViewModel, ...
        dependencies: ["settingsViewModel"],
        elements: ["#settings_plugin_backupscheduler"]
    });
});