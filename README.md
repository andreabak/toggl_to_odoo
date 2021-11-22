# toggl_to_odoo

**toggle_to_odoo** is a tool to synchronize entries from **Toggl Track** to timesheets in an **Odoo** database

## Setup

###### Install

- Clone this repository
- Install dependencies for your python3 environment:
   ```sh
   pip3 install -r requirements.txt
   ```
- [Setup Toggl CLI config](https://toggl.uhlir.dev/#configuration)
- Adapt converters for your use, [these converters](https://github.com/andreabak/toggl_to_odoo/tree/odoo-abk-converters/converters) are a good place to start

###### Toggl side

If using the suggested converters, you will need to define several Toggl projects and add them to an "Odoo" client under Toggl.  
Tasks should be in the format `[odoo task id] title` and filed under a project named "Odoo-psbe" or "Odoo-maintenance"


Look into [converters/odoo_common.py](converters/odoo_common.py) to get an idea of the others projects you need.  
For exemple *Misc* entries have to be filed under "Odoo-misc"

## Guide

### Usage

To run the synchronization, run :
```sh
python3 -m toggl_to_odoo upload toggl2odoo https://www.odoo.com openerp history
```

