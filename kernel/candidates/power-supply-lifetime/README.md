# Offline power-supply producer retirement candidate

The `power-supply-lifetime` profile adds patch 0037 only to explicitly requested
offline tests. Image inputs and the ordinary power-supply driver check retain
their original queue. Run `task test:power-supply-lifetime` for actual-source
native/ARM regressions and `task test:power-supply-kunit` for the original and
reordered real Linux teardown kernels. Report 222 retains the historical
receipts; later image integration and physical qualification remain separate.
