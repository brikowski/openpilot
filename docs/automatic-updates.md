# Automatic update installation

A downloaded update installs automatically once the updater has finished staging it and fresh,
valid device and Panda messages confirm that OpenPilot is offroad and every connected Panda
reports ignition off. Being disengaged or blocked from starting does not by itself qualify.
No tap on "Reboot and Update" is required. Installation uses the existing graceful manager
shutdown, device reboot and launcher update activation.

Automatic installation respects `DisableUpdates` and pending shutdown, uninstall or reboot
requests. It waits while the updater is checking, downloading or finalizing. The finalized
update must match the selected target branch, retain its consistency marker and pass the
launcher's local-checkout protection. A missing staging marker, existing install backup,
inspection failure or changed checkout defers the reboot.

The update workflow and its paired submodule revision still determine what is installed.
Publication, download and installation remain separate steps. The decision is to keep this
software-tested installation policy; device installation and subsequent startup health require
separate verification. Vehicle control and tuning are unaffected.
