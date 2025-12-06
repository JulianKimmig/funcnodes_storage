feat(sql): add conditional delete and proper value decoding

- allow DeleteData to delete rows via filters and avoid auto-trigger
- fix retrieval JSON decoding and add tests/config fixture coverage
- make get_tables async to return resolved list
