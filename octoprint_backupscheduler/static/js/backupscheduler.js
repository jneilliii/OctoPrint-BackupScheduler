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
    }

    OCTOPRINT_VIEWMODELS.push({
        construct: BackupschedulerViewModel,
        // ViewModels your plugin depends on, e.g. loginStateViewModel, settingsViewModel, ...
        dependencies: [ "settingsViewModel" ],
        elements: [ "#settings_plugin_backupscheduler" ]
    });
});
