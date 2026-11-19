# Quick test run

App: http://localhost:8000 (see the README for setup). Log in at `/login/` with the **username**.
Password for every demo account: the `DEMO_USER_PASSWORD` you set in `.env`.
Use a normal window for one role and a private window for another.

| Role | Username |
|---|---|
| Resident | `demo_resident_01`, `demo_resident_02` |
| Call Center Staff | `demo_officer_01` |
| Technician | `demo_technician_01` (Technical Services), `demo_technician_02` (Pest Control) |
| Admin | the account from `createsuperuser`, at `/admin/` |

Test data: building **Dormitory A**, room **A101**. Bad room: **A999**.
📷 = take a screenshot for the report. Tick each box as you go.

---

## 1. Resident submits (`demo_resident_01`)
- [ ] **New request**: category, subcategory, Dormitory A, A101, tick the room confirmation, title, description, urgency → Submit. Ticket `MR-2026-…` appears, status **Submitted**. 📷 form + ticket page
- [ ] Submit again with room **A999** → room error, no ticket.
- [ ] Submit with a photo → ticket lists the photo.
- [ ] **My requests** shows only your tickets. 📷

## 2. Staff review and assign (`demo_officer_01`)
- [ ] **Queue**: the new ticket is there, tiles and "Open … ago" shown. 📷
- [ ] Search **Room** `A1`, then **Ticket number**, then **Student ID** `demo_resident_01` → each narrows the list. 📷 room search
- [ ] Tick **Confirm room and building** → **Begin review** → status **Under review**.
- [ ] Set priority **High** → Save.
- [ ] **Choose unit and technician** → Technical Services + `demo_technician_01` → Confirm → status **Assigned**. 📷
- [ ] Pick a technician from another unit → refused.
- [ ] On another ticket, **Reject** with a reason → status **Rejected**. Empty reason refused.

## 3. Caller entry (`demo_officer_01`)
- [ ] **New ticket**: caller `demo_resident_02`, Phone, Dormitory A, A102, tick "I verified…", fill in, leave unit empty → Submitted. 📷
- [ ] Repeat with a unit, technician and priority **Urgent** → created **and assigned** in one step. 📷
- [ ] Choose a unit without a priority → refused.

## 4. Technician (`demo_technician_01`)
- [ ] **My work** shows only your assigned tickets.
- [ ] **Start work** → **In progress**. 📷
- [ ] **Hold**: reason + expected date → status **On hold**, hold box shown. 📷
- [ ] **Resume work** → back to **In progress**.
- [ ] **Complete** with notes, signature box unticked → ticket **Closed**, "Completed without the resident present". 📷
- [ ] Open the closed ticket URL again → 404.

## 5. Resident follow-up (`demo_resident_01`)
- [ ] Open the closed ticket: **Completion record** and "Reopen window open · 3 days left". 📷
- [ ] Add a comment → refused (ticket closed).
- [ ] **Verify** with rating 4 → recorded, ticket stays Closed.
- [ ] **Reopen** with a reason → status **Assigned**. 📷 history
- [ ] Add a comment now → accepted.

## 6. Live updates
- [ ] Staff window open on a ticket. In another window, post a comment as the resident. It appears on the staff window within ~10 s with no refresh. 📷

## 7. Privacy
- [ ] As `demo_resident_02`, open a ticket URL belonging to resident 01 → 404.
- [ ] As `demo_technician_02`, open a ticket assigned to technician 01 → 404.
- [ ] As a resident, open `/officer/dashboard/` → 404.

## 8. Unit results
- [ ] Staff: **Unit results** lists all units. Technician: only their own unit. 📷

## 9. Admin (`/admin/`)
- [ ] Sidebar shows Units, Reports, Comments, Verifications. 📷
- [ ] **Users → Add user**: Call Center Staff with name, email and role → saved, can log in.
- [ ] Add a Technician with **no unit** → "must belong to a unit".

## 10. API
- [ ] Open `/api/docs/` → login, logout, me and CSRF are listed. 📷
- [ ] Log in as a resident, then `/api/auth/me/` shows the role.

## 11. Automated tests
```bash
python manage.py test
```
- [ ] Last line says `OK` (about 200 tests). 📷

---

**Result:** ____ passed / ____ failed. Write any failed step here: ____________
