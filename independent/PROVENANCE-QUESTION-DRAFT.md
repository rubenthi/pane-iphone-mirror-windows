# Approved public question — posted

Posted with explicit user approval as [jkcoxson/idevice issue 145](https://github.com/jkcoxson/idevice/issues/145) by `rubenthi` on 2026-11-08. This text is a request for factual provenance clarification, not an allegation.

Title: Clarification of core_device provenance under the MIT license

Body:

> I am evaluating idevice for a new Windows application whose delivered dependency policy excludes GPL/LGPL/AGPL code. Thank you for clarifying in issue #115 that MIT applies to all repository commits.
>
> I noticed that `idevice/src/services/core_device/mod.rs` says “Ported from pymobiledevice3”, while pymobiledevice3 is GPL-3.0-or-later. Could you clarify whether that portion is an independent implementation of protocol behavior, a translation of source expression with permission, or covered by another licensing arrangement? If permissions or a prior explanation exist, a link would help us document the provenance accurately.
>
> I am specifically trying to understand any inherited licensing obligations, rather than treating a package-level MIT declaration as sufficient evidence by itself. We have not shipped this dependency in the new application.

The approved text above was posted unchanged. Posting the question does not resolve the provenance review or clear the dependency for release.
