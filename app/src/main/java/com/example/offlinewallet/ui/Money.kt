package com.example.offlinewallet.ui

import java.math.BigInteger
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

fun rupees(paise: Long): String {
    val amount=BigInteger.valueOf(paise).abs()
    val parts=amount.divideAndRemainder(BigInteger.valueOf(100))
    val whole=parts[0].toString()
    val tail=whole.takeLast(3)
    val prefix=whole.dropLast(3).reversed().chunked(2).joinToString(",").reversed()
    return (if(paise<0) "−" else "") + "₹" + (if(prefix.isEmpty()) tail else "$prefix,$tail") + "." + parts[1].toString().padStart(2,'0')
}
fun confirmedTime(epoch: Long): String = DateTimeFormatter.ofPattern("d MMM yyyy, HH:mm").withZone(ZoneId.systemDefault()).format(Instant.ofEpochMilli(epoch))
