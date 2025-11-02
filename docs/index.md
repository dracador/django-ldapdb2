# Introduction

`django-ldapdb2` is a **Django database backend for LDAP**. It aims to feel like Django’s ORM while supporting LDAP-specific features such as server-side sorting and paging (SSSVLV), LDAP-aware fields, and pragmatic transaction blocks.

**Highlights**

- **LDAP as a Django DB backend** – query with familiar ORM patterns  
- **SSSVLV** for server-side ordering and pagination  
- **Transactional write blocks** via `transaction.atomic(using="ldap")` (best-effort)  
- **LDAP-aware fields** and objectClass handling  
- **checkdb / inspectdb** helpers  
- Optional **“explain as LDIF”** style debugging

---

## Who is this for?

- Django developers who need to read/write LDAP entries with ORM ergonomics.
- Teams integrating with OpenLDAP, Active Directory, or Samba AD.
- Projects that want server-side sorting/pagination and predictable write flows.

---

## Get started

- **[Installation & Setup](installation.md)**
- **[Quickstart](quickstart.md)**
- **Guides**
  - **[Models & Fields](guides/models-and-fields.md)**
  - **[Querying LDAP](guides/querying.md)**
  - **[Transactions & Atomicity](guides/transactions.md)**
  - **[Ordering & Pagination (SSSVLV)](guides/sssvlv.md)**
  - **[Debugging & Logging](guides/logging.md)**
- **Server notes**: [OpenLDAP](servers/openldap.md), [Active Directory / Samba AD](servers/ad.md)  
