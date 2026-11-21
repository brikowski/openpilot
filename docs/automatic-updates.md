# Automatic update installation

A downloaded update installs automatically once the updater has finished staging it and fresh,
valid device and Panda messages confirm that OpenPilot has stayed offroad with every connected Panda
reporting ignition off for 60 seconds continuously. Being disengaged or blocked from starting does
not by itself qualify. No tap on "Reboot and Update" is required. Installation uses the existing
graceful manager shutdown, device reboot and launcher update activation.

Automatic installation respects `DisableUpdates` and pending shutdown, uninstall or reboot
requests, and defers while Driver View or live streaming is active, while device thermals are
overheated or critical, when free disk space is below 5%, or while an in-car harness reads vehicle
battery voltage below 11.8 V (USB bench power is not blocked by the 12 V check). It waits while the
updater is checking, downloading or finalizing. The finalized update must match the selected target
branch, actually change the installed branch or commit, retain its consistency marker and pass the
launcher's local-checkout protection. A missing staging marker, existing install backup, inspection
failure or changed checkout defers the reboot and throttles repeated staging checks to once every
30 seconds.

The update workflow and its paired submodule revision still determine what is installed.
Publication, download and installation remain separate steps. The decision is to keep this
software-tested installation policy; device installation and subsequent startup health require
separate verification. Vehicle control and tuning are unaffected.
