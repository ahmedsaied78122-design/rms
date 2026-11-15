# First-run Master and Slave setup

The first Setup Wizard screen selects `Master` or `Slave`. Use matching RMS source
on both sites and Arab Streaming 0.2.1 or later. Installation does not select a role
or connect an existing site automatically.

## Master

Choosing Master continues the standard Frappe/ERPNext language, user and company
slides. Successful setup configures the Master role and enables its streaming
engine. The operator still creates the Stores/Branches and issues an enabled
Instance Key for an approved non-Administrator integration user.

## Slave

Choosing Slave opens connection setup instead of the company slides. Enter:

- The Master's HTTPS URL.
- An enabled master Instance Key's Access Key and Secret (not a login password).
- A Store selected after **Test connection and load Stores**.
- This Slave's public HTTPS URL.

The master offers only enabled Stores visible to the key's user, linked to enabled
Streaming Branches not already assigned to another peer. Only Administrator may
run first-time local setup. Existing companies/connections cannot be replaced by
this workflow. The selected Store is checked again on the server when starting.

The slave creates an app-managed local integration user, stores the master Secret
in the native encrypted Password field, links through the existing streaming
protocol, installs the master's published policy, and queues the native immutable
initial copy. The policy must allow incoming Company, Store and Branch. Only
inbound reference/setup types are selected; financial history is not selected.

Company identity scaffolds break Company/Account cycles, using master-supplied
metadata and ordinary Company validation without generating a different local
chart of accounts. The full source Company snapshot then updates those identities.
During authenticated first-time setup only, the Store's optional preparation-area
and POS-profile links, and a Brand's optional menu table, are deferred until their
dependent records can reference the new parent. The complete fields are restored
through normal save validation in the same transaction. ERPNext's parentless root
Account/Cost Center convention is accepted only for a new, authenticated bootstrap
root; every other mandatory field and normal controller check remains active.
Normal company behavior remains in place outside this bootstrap.

The wizard displays copy progress and offers Resume after failure. A refresh
returns to the saved connection without asking for the Secret again. The setup
completion flags are changed inside the successful copy transaction only after
the full Company snapshot is recorded and the received Store matches the selected
company/branch. Global company/currency defaults come from that Company. A failed
or queued copy does not unlock the normal application as a completed setup.

The non-secret resume identity is in `site_config.json` under `rms_slave_setup`;
encrypted credentials remain in Master Instance. Site-specific values never belong
in Git. Master/Slave data ownership and multi-peer synchronization acceptance are
separate from this first-run workflow.

## Verification

An isolated verified-HTTPS Master/Slave run completed at 100%, with one Company,
82 Accounts, two Cost Centers, five Warehouses, one Store and one Preparation Area
on each site. The Store/Preparation Area cycle was restored, the default company
matched, and POS/Sales Invoice and GL Entry counts remained zero. A separate
rolled-back test inserted/restored a Brand/Menu table cycle through native
validation. Browser checks covered the first role screen, native Master slides,
the company-free Slave form and real Instance Key Store discovery. These are
bootstrap checks, not a financial lifecycle or 38-peer load certification.
