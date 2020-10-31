/*
 * View model for Backup Scheduler
 *
 * Author: jneilliii
 * License: MIT
 */
$(function() {
    function BackupschedulerViewModel(parameters) {
        var self = this;

        self.settingsViewModel = parameters[0];
        self.cert_saved = ko.observable(false);
        self.show_time = ko.pureComputed(function(){
            return self.settingsViewModel.settings.plugins.backupscheduler.backup_daily() || self.settingsViewModel.settings.plugins.backupscheduler.backup_weekly() || self.settingsViewModel.settings.plugins.backupscheduler.backup_monthly()
        })

        self.onSettingsBeforeSave = function(){
            if(!self.settingsViewModel.settings.plugins.backupscheduler.daily.time().match(/([01]?[0-9]|2[0-3]):[0-5][0-9]/)){
                self.settingsViewModel.settings.plugins.backupscheduler.daily.time('00:00')
            }
            if(!self.settingsViewModel.settings.plugins.backupscheduler.weekly.time().match(/([01]?[0-9]|2[0-3]):[0-5][0-9]/)){
                self.settingsViewModel.settings.plugins.backupscheduler.weekly.time('00:00')
            }
            if(!self.settingsViewModel.settings.plugins.backupscheduler.monthly.time().match(/([01]?[0-9]|2[0-3]):[0-5][0-9]/)){
                self.settingsViewModel.settings.plugins.backupscheduler.monthly.time('00:00')
            }
        }
    }

    OCTOPRINT_VIEWMODELS.push({
        construct: BackupschedulerViewModel,
        // ViewModels your plugin depends on, e.g. loginStateViewModel, settingsViewModel, ...
        dependencies: [ "settingsViewModel" ],
        elements: [ "#settings_plugin_backupscheduler" ]
    });
});
