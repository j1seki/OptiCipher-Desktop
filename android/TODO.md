# Android TODO — v1.4.3

- [ ] 1. Rename activation buttons to say what they do
      ("Encrypt queued files", "Decrypt queued files", "Turn on auto-encrypt", …)
- [ ] 2. Split folder watch into two independent jobs
      - Card 2: Folder watch — **Encrypt** new files
      - Card 3: Folder watch — **Decrypt** new files
      - each with own folder, output, passphrase, interval, switch
- [x] 3. Folder access permissions (not just gallery/images)
      - use SAF per-folder grants (no all-files access), optional media/notification
        prompts, with status dialog + settings links
- [ ] 4. Folder watch: option to process **existing** images on start
      (not only files that appear later)
- [ ] 5. Conflict policy when the output file already exists:
      ask / overwrite / skip (background jobs use skip unless overwrite is chosen)
- [ ] 6. Build locally (unit tests + assembleDebug)
- [ ] 7. Push built APK to 192.168.1.183:35131 (device already authorised)
