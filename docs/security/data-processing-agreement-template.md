# Data Processing Agreement (template)

Template written 2026-11-16 for Versnq Core customers who need a DPA (GDPR Art. 28, DPDP Act
2023). **A lawyer must review it before it is signed.** Fill in the [brackets].

**Between** [Customer legal name] ("Controller", our customer) **and** [Versnq legal entity]
("Processor", provider of Versnq Core).

1. **Subject.** The Processor hosts and processes personal data of the Controller's leads,
   customers and users only to provide Versnq Core, on the Controller's documented
   instructions (the product's settings and the main agreement).
2. **Data and people.** Contact details, messages, call records and recordings, documents,
   invoices and payments of the Controller's leads and customers; names, emails and sign-in
   records of the Controller's users.
3. **Duration.** For the main agreement. Afterwards the Controller can export everything
   (Settings → Security → Export everything) within 30 days; then the data is deleted,
   including from backups within [backup retention] days.
4. **Confidentiality.** People who can access the data are bound by confidentiality.
5. **Security (Art. 32).**
   - Each company's data is kept apart by row-level security in the database.
   - HTTPS only.
   - Passwords are hashed, and connected-account keys are encrypted.
   - Optional two-factor sign-in, an IP allowlist and idle sign-out.
   - Sign-in history and an audit log.
   - Access by role.
   - Backups [describe].
6. **Sub-processors.**
   - **Now:** [hosting provider and location], [email provider].
   - **When the Controller connects them:** Meta (WhatsApp), Twilio, payment gateways,
     and Versnq ACE.
   - The Processor tells the Controller before adding a new sub-processor; the Controller
     may object.
7. **Requests from people.**
   - The product lets the Controller answer access requests (a lead's "Download this
     person's data") and erasure requests ("Erase this person").
   - The Processor helps with requests the product can't answer by itself.
8. **Breaches.** The Processor tells the Controller without undue delay, and in any case
   within [24/48] hours of becoming aware, with what is known (see our breach runbook).
9. **Transfers.** Data is stored in [country/region]. Transfers outside it use [standard
   contractual clauses / adequacy], where required.
10. **Audits.** The Processor provides the information needed to show compliance, and allows
    reasonable audits on [notice].
11. **Deletion or return** at the end, as in point 3.

Signed: ____________ (Controller) ____________ (Processor) Date: ________
