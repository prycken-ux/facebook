# Read-only probe of the actual Page Reels tab

The user's Windows result confirms a production comment on fb10/page02 Reel
1500593451890233 was seen after reload. This known video is the probe's check;
it is never commented again by the probe.

The first live actual-tab probe navigated to the correct owner profile with
sk=reels_tab, but the observed Reels aria-selected flag remained false. Version 1
had gated link reading on that flag, so it never attempted reading links and its
zero count did not establish an empty video list. Version 2 separates observation
of the tab flag, the actual owner/route, main-content links and all visible-page
video links. Missing selection markup no longer suppresses read-only collection.

Only fb10/page02 Drascreflo Chajundfro (owner 61595204068114) is opened. Exactly one
visible Page Reels tab must exist before clicking; the global Reels navigation is
not substituted. The observed route retains only id/sk/locale in diagnostics.
Canonical visible video links, main versus full-page counts, role-link counts and
presence of the known successful video are reported. These are candidate URLs,
not an authorization to comment on a guessed video; no candidate is selected for
sending. The source owner/caption/time checks would still be needed for later
batch binding.

Publication, comment and retry journals, configuration and media are unchanged;
only a filtered diagnostic JSON is saved. Active tasks block profile access and
only a normal close request is made for the exact fb10 Chrome profile. The pinned
abandoned-PID helper never resumes any old task. No raw-response or credential
export, upload, comment, marking, CSV or Notepad occurs.

Five local Chromium checks cover normal actual-tab navigation, valid route plus
missing selected markup, distinction between main-content and other visible video
links, refusal of ambiguous tabs/global Reels navigation and byte-identical business
journals/config after the probe. These fixtures do not claim that the live Page's
remaining video links have already been recovered.
