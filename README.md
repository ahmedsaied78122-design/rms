# RMS Frappe app

First-run setup now starts with Master/Slave selection. Master keeps the native
company wizard; Slave uses a master URL, Instance Key and Store, then copies its
setup through Arab Streaming. This requires Arab Streaming **0.2.1+** and matching
RMS code on the master. See [first-run setup](docs/SETUP_WIZARD.md).

Custom Restaurant and Retail operations app for ERPNext. All custom DocTypes,
controllers, Desk pages, translations and migrations belong here; ERPNext core
DocTypes remain untouched.

Use one release group with this installation order:

1. `frappe`
2. `erpnext`
3. `arab_streaming`
4. `rms`

ERPNext declares its Frappe dependency; Arab Streaming requires ERPNext; RMS
requires ERPNext and Arab Streaming. Bench compatibility metadata targets the
Frappe/ERPNext v15 release train and Arab Streaming 0.2.x. The current RMS site
runs Frappe/ERPNext 15.122.0 with Python 3.10. These checks do not certify v16.

For a fresh site after all four app repositories are available in the Bench:

```sh
bench --site YOUR_SITE install-app rms
```

The native installer installs the required applications first. On an existing
RMS site, install the missing dependency explicitly:

```sh
bench --site YOUR_SITE install-app arab_streaming
```

Installing Arab Streaming adds its setup screens and schema. Master/Slave roles,
peer connections and synchronization rules are separate site configuration;
installation alone does not activate remote synchronization. RMS's local sync
journal remains a separate facility.

RMS also seeds an editable general streaming profile: 41 master-to-branch rules,
12 branch-to-master rules and 5 bidirectional customer/reference rules. It adds
only the approved optional Store-to-Branch field and app-owned branch routing;
it does not select a site role, enable transport, provision credentials or pair
a remote site. Existing operator changes and slave-published policies are kept.
New slave connections receive 46 initial-copy suggestions without automatically
copying financial history. See [the streaming configuration guide](docs/STREAMING_CONFIGURATION.md)
and its Arabic workbook for ownership, exclusions, validation and acceptance limits.

A subsequent readiness review identified two open capabilities: independent
per-direction action restrictions for Both rules, and explicit master relay of
slave-originated shared records to other slaves. The current profile does not
certify multi-slave shared-record distribution. See the guide's readiness review.
