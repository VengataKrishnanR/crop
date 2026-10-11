## Condition expression language ("Other Logic")

```
serviceCodeList.contains("DD")          service code present
!serviceCodeList.contains("DD")         service code absent
incotermCodeList.contains("DDP")
destinationServiceArea.contains("AUH")
OriginCountry=="AU"                     equality on a field
hscode("inboundHsCode","<blank>")
matchCiMask("shortCode|==|SDT","value|!=|<blank>")
```

Operators: `&&` `||` `!` `==` `!=`

- matchCiMask arguments are pipe-delimited `field|op|value` triples. Comma-delimited forms exist in old material and are wrong; never copy them.
- `&&` binds tighter than `||`. Always bracket mixed expressions to state intent.
- Call `check_expression` on every expression before you put it in your output, and fix anything it reports.
