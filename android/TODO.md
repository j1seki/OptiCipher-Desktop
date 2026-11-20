# Android release verification

The Android workflow runs unit tests and lint and builds the APK. On an Android
device or emulator, verify the following before publishing a release.

- Queue a PNG and a corrupt image. Encrypt the batch, verify the valid output
  with the correct and wrong passphrases, and decrypt it back to the original
  pixels. Rotate the device during a batch and check that progress and result
  links are still available.
- Save to the private folder and find the output under **OptiCipher private** in
  the system picker. Open and share the result through a read grant.
- Enable independent encrypt and decrypt watches with separate test inboxes.
  Check **Run now**, **Include existing**, **Skip** and **Overwrite**. Include a
  bad ciphertext before a valid one and confirm the valid file still processes.
- Set a weekly schedule near the current local time and verify that it fires
  once, including with the activity closed. Change the device time zone and
  verify that the next check follows the local schedule.
- Install a release-signed build over the previous release. Confirm existing
  folder grants, remembered watch settings and private files are accessible.
