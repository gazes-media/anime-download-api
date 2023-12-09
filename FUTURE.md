# The objectives of this project

As the current version need to download in a tmp directory the video file before being able to set a working player inside Discord, it is not very convenient... We need to wait a few minutes before being able to play the episode!

An ideal solution would be to convert the video on the fly and return it.

In our case, a M3U file consist on a playlist of ~2s .TS files, that are encoded using H254.
Discord is **only** able to read MP4, MOV and WEBM video files.
MP4 and MOV files are compatibles with H254, not WEBM.

This is important, because if we use the same codec, we can transmux the files instead of transcode them, so it is way more efficient.

The problem is : as long as I know, an MP4 file must know its length and its size before being play (these informations are contained in the headers).
I guess it's the same for .MOV files.

That being said, MP4 files can be fragmented.
The structure of an MP4 fragmented file is :

```
ftyp
moov
moof
mdat
moof
mdat
moof
mdat
...
```

ftyp and moov boxes contains informations about the video dimensions, the quality, and some other informations...
And also an index of the number of moof/mdat boxes that follow. I think this index could be blank so the player will just try to get the next boxes, but I'm really not sure, and my tests didn't confirm that neither.

A solution would be to build this indexe, because we are in theory able to know the number of ts video file and their duration. But I'm really not sure how.

My tests ended with the following scenarios :

- We use the first .ts file to build the ftyp and the moov boxes, with the ffmpeg "empty_moov" flag. So in theory, the moov file is empty and doesn't contain any index (thats probably wrong, as you will see later)
- We use all the following .ts files and we build an fmp4, then we remove all the boxes except `moof/mdat`
- When Discord request the URL, we return the ftyp, the moov, then all the moof/mdat boxes in a stream.

But, if we include the moof/mdat part of the first .ts file, the Discord player read 2s then stop. If we omit the first moof/dat related to the .ts file, the player read nothing. This mean the ftyp/moov are associated with the moof/mdat boxes of the first .ts file.

I will not continue this project for now, because of a lack of time. But I'm still sure there is a way.
