# Guida Backup Proxmox

## Procedura backup vzdump
Per eseguire il backup di un container LXC usare vzdump con compressione zstd.
Il comando è: vzdump 137 --storage nas-backup --mode snapshot --compress zstd

## Ripristino
Il ripristino usa qmrestore o pct restore a seconda che sia VM o container.
La destinazione tipica è local-lvm.

## Pianificazione
I backup sono schedulati ogni notte alle 3:00 via cron sull host.