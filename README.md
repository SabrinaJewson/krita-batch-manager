Krita plugin for easy management of entire folders of `*.kra` files.
Supports:
- Importing and exporting images in batch.
- Easy navigation between images.

# Installation

1. Download this repository, e.g. using `git clone` or “Code → Download ZIP” on GitHub.
1. In Krita, go to to Settings → Manage Resources, then click “Open Resource Folder”.
1. Make a folder called `pykrita` in the resource folder, if it doesn’t already exist.
1. Copy the `krita_batch_manager.desktop` file into the `pykrita` folder.
1. Make a folder called `krita_batch_manager` in the `pykrita` folder.
1. Copy the `krita_batch_manager/__init__.py` file into the newly made `krita_batch_manager` folder.
1. Go to Settings → Configure Krita → Python Plugin Manager and check “Batch Manager”.
1. Restart Krita.
1. Go to Settings → Dockers, and you should be able to check “Batch Manager”.

If on Unix, you may want to use symlinks to keep things up-to-date automatically.
For example:

```
mkdir ~/.local/share/krita/pykrita/krita_batch_manager
ln -s "$PWD"/krita_batch_manager.desktop ~/.local/share/krita/pykrita
ln -s "$PWD"/krita_batch_manager/__init__.py ~/.local/share/krita/pykrita/krita_batch_manager
```

# Usage

![](demo.webp)

Batch Manager will appear as a docker.
You can see it displays a list of all the `.kra` files in the current directory.
You have several buttons available to you:
- The left and right arrows will navigate to the previous and next images respectively.
- The plus button batch-imports several images as `.kra` files in the current folder.
- The refresh icon updates the contents of the list
	(in case you e.g. change the contents of the folder with a means external to Batch Manager).
- The folder icon changes the current folder.
	Note that if you open a `.kra` file, the current folder will always be reset
	to the folder that `.kra` file is in.

For each file in the list:
- Double-click to open it.
- Right-click to delete or rename it.

Below the list, you can configure the export directory and export settings,
which are the same for all the `.kra` files in the list.
Once you have chosen a directory, click the “Export” button to actually perform the export.
Export options can be changed with the button on the right.

If only some `.kra` files have been changed,
export functionality will make sure to only re-export the changed ones.
This makes incremental exports fast.

# Development

Getting started:
- Run `uv sync`.
- Run `touch ~/.local/share/krita/pykrita/krita_batch_manager/dev_mode`.

Useful commands:
- Typechecking: `uv run mypy __init__.py`

License: EUPL
