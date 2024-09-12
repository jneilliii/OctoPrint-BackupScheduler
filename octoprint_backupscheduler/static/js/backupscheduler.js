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
        self.cert_saved = ko.observable(false);
        self.show_time = ko.pureComputed(function () {
            return self.settingsViewModel.settings.plugins.backupscheduler.backup_daily() || self.settingsViewModel.settings.plugins.backupscheduler.backup_weekly() || self.settingsViewModel.settings.plugins.backupscheduler.backup_monthly()
        })
        self.sendTestEmailRunning = ko.observable(false);


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
            // NotificationMessages
            debugger
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
                            text: gettext("Backup failed as the mount was missing!"),
                            type: "error",
                            hide: false
                        });
                        break;
                    case "backup_failed":
                        new PNotify({
                            title: gettext("Backup failed"),
                            text: gettext("Backup failed! Please check, why the backup could not be created!"),
                            type: "error",
                            hide: false
                        });
                        break;
                }
            }
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
                // self.filesViewModel.requestData({force: true});
                self.sendTestEmailRunning(false);
            }).fail(function (data) {
                self.sendTestEmailRunning(false);
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
