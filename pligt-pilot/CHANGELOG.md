# Changelog – Pligt-pilot

Newest first. Each version lists what changed since the one before.

## 0.25.0 – 2026-11-21

- A child can only take one free task at a time: the others show "Finish your chore before you take a new one" until it is reported done. Tasks you give yourself don't count. Can be switched off in Settings

## 0.24.2 – 2026-11-21

- Overview, "Right now": tasks you gave straight to a child today (also one-off tasks, each their own) now show too - one line per task with the children's names. From the ⋯ menu you can take it from a child, or move it when only one has it

## 0.24.1 – 2026-11-21

- Overview, "Right now": a first-come task you sent out shows up at once, with who can take it ("Free · Emil and Sofie" or "Free for everyone"). It switches to the child's name when taken, and can be taken back from the ⋯ menu

## 0.24.0 – 2026-11-21

- Give a task: "Pick several – first come, first served" lets you choose which children may take it. Only they see it, and it disappears for the others as soon as one takes it
- One-off task: with two or more children picked, choose "Each their own" or "First come, first served"

## 0.23.0 – 2026-11-20

- Overview, "Right now": a free house job (nobody has taken it) can now be deleted from the ⋯ menu. The machine rule stays, so the next run gives a new one

## 0.22.1 – 2026-11-20

- Home Assistant now downloads the ready-made app (amd64/aarch64) instead of building it on your machine: faster updates and no build leftovers on the disk

## 0.22.0 – 2026-11-20

- One-off task: write a task and a price on the overview and send it only to the children you pick, for today - it is not saved under Tasks and is cleared when done

## 0.21.1 – 2026-11-19

- Overview: "Per month" and "Recent" are folded away and open with a tap

## 0.21.0 – 2026-11-19

- The child's page grows with the child: a playful look for 0-8 (big pictures and a big tick button), a tidy one for 9-12 and a dark, plain checklist for 13+
- Chosen by age, or set per child under Children ("Look of the child's page")
- Tasks come right after the top card; suggesting a task and messages moved to the bottom

## 0.20.1 – 2026-11-19

- House: the long list of every meter is gone - "Use another meter" opens a sheet with search, and meters that are unavailable or don't show watts are left out

## 0.20.0 – 2026-11-19

- New overview: header with what waits, what's in progress and what to pay out; approve everything from one child with one tap
- "In progress" shows every job a child has taken; the three dots give it to another child or take it back
- Quick buttons as small tiles, children side by side with a ring for the week, the boss as a bar, floating menu

## 0.19.1 – 2026-11-19

- "Write with AI" is more thorough: 5-8 concrete steps in order (toilet, room desk, under the bed and so on)
- Extra steps for older children ("11+: Descale the tap"), shown only to children of that age
- "Done when" at the end, shown in its own box in the child's app

## 0.19.0 – 2026-11-19

- "How to do it" on each task: a short step list the child sees under the task
- "Write with AI": Home Assistant's AI (ai_task) writes the steps for the youngest child; tries the next AI if one is busy
- Machine chores get fixed steps
- "Released at": a fixed task can appear at a set time, and the children get a message
- "Sick today": school chores (lunch box, school bag, homework) disappear for the day without a deduction; back to normal tomorrow
- Children can say "I am sick today" in their app; a parent approves it
- Quick buttons always let you pick one child or everyone

## 0.18.4 – 2026-11-18

- Door sensor list: sensors named after the machine first

## 0.18.3 – 2026-11-18

- Reads Home Assistant's sensors in a big home too (states via /api/states, rooms from a small template) - the door, meter and suggestion lists were empty

## 0.18.2 – 2026-11-18

- Pick a machine's door sensor in a sheet: search by name, room or id, the machine's room first, open/closed live

## 0.18.1 – 2026-11-18

- A machine rule finds its door sensor by itself when exactly one fits

## 0.18.0 – 2026-11-18

- Children suggest chores with a picture
- Edit machine rules
- 'Right now' on the overview
- Children take machine chores here from Hus-chat

## 0.17.0 – 2026-11-18

- Simpler tasks page: two groups, one line each, edit in a sheet
- Chosen days stay

## 0.16.0 – 2026-11-18

- Tasks are fixed (with days) or given by hand
- Names match on first word

## 0.15.0 – 2026-11-18

- Add your own quick buttons, long press removes
- The cook is told on the day

## 0.14.0 – 2026-11-18

- Docs: quick buttons, seasons and weather
- Quick buttons: each child their own, or one of them

## 0.13.0 – 2026-11-18

- Quick buttons to give a task, seasons and frequency by themselves, weather

## 0.12.0 – 2026-11-18

- Machine tasks clear by themselves, weekly minimum, unpaid duties, cook day
- Works with Hus-chat and Madplan

## 0.11.1 – 2026-11-18

- Parents' page: say when the link works away from home
- New picture of the children tab

## 0.11.0 – 2026-11-18

- Links that work away from home through Home Assistant, install button

## 0.10.2 – 2026-11-17

- Small fixes

## 0.10.1 – 2026-11-17

- Small fixes

## 0.10.0 – 2026-11-17

- Small fixes

## 0.9.2 – 2026-11-17

- Fix icon test

## 0.9.1 – 2026-11-17

- The parent page can be installed as an app

## 0.9.0 – 2026-11-17

- Small fixes

## 0.8.0 – 2026-11-17

- Small fixes

## 0.7.0 – 2026-11-17

- Small fixes

## 0.6.0 – 2026-11-17

- Small fixes

## 0.5.1 – 2026-11-17

- Date of birth is chosen with day, month and year instead of a calendar

## 0.5.0 – 2026-11-17

- Small fixes

## 0.4.2 – 2026-11-17

- Find home network address: permission for Supervisor and fallback via Home Assistant

## 0.4.1 – 2026-11-17

- Child links use the home network's address, not the address the parent opens the app from

## 0.4.0 – 2026-11-17

- Web push directly from the children's link with https certificate

## 0.3.2 – 2026-11-17

- Find the meter for the machines automatically

## 0.3.1 – 2026-11-17

- Free notifications to the children's phones via ntfy

## 0.3.0 – 2026-11-17

- Date of birth, house rules, messages, photo, streaks, badges, family goals, pocket money, deductions, perfect week, month overview

## 0.2.1 – 2026-11-17

- Suggestions based on appliances in the house (washing machine, tumble dryer and others)

## 0.2.0 – 2026-11-17

- Pause, tasks for specific children, undo and history, savings goals, several times per period

## 0.1.1 – 2026-11-17

- Fix Dockerfile: use fixed Python base image
- Suggestions are off by default and can be edited
- Tasks can be edited

## 0.1.0 – 2026-11-17

- Start: README, license and design draft of the screens
- First version: child link, tasks, approval, suggestions and hero of the week
