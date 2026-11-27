
# Procedure revision 2: restoration preview

This revision extends the old skill's operation vocabulary with exactly one
additional local operation: {"kind":"activate","role":"Review restoration preview"}.
On a restoration task (excluded=false), IF the observed form contains this button,
insert it AFTER writing Draft excluded and BEFORE Save excluded. Its observed
effect must be Restoration preview="confirmed". Never skip this step or reuse a
preview from another scope/draft. The host refuses Save if the preview is missing
or has been invalidated; stop without retry in that case.

On exclusions (excluded=true), or old forms without this button, keep the original
eight-step procedure. Do not invent a new review button on those forms. The new
step is a technical local preview check, not new financial permission. All old
approval, identity, independent readback, no-retry and JSON-output rules remain.
