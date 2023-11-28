<img src="https://bannermd.airopi.dev/banner?title=Discord%20M3U%20stream&desc=Stream%20M3U%20videos%20inside%20Discord&repo=gazes-media/anime-dl" width="100%" alt="banner"/>

<p align="center">
  <a href="https://www.buymeacoffee.com/airopi" target="_blank">
    <img alt="Static Badge" src="https://img.shields.io/badge/Buy_me_a_coffee!-grey?style=for-the-badge&logo=buymeacoffee">
  </a>
</p>

<h1 align="center">Discord M3U stream</h1>

The goal of this project is to be able to stream a M3U files inside a Discord video player.

The first idea was to use ffmpeg to directly convert the .m3u file into a MP4 file, and return the MP4. Because transcoding can take some time, the conversion consist on 2 endpoints :

- /download?url=https...&quality=high
  This endpoint then starts the conversion process, and return informations containing the progression.
- /result?id=...
  This endpoint can be used after the conversion is done.

Results are cached during 24h.

But while this could works, it is not ideal. We first need a download etc.
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

To conclude : this project is aborted, doesn't works, and even the first strategy isn't fully implemented because it was not a very convenient way to proceed.

## Support, Feedback and Community

You can reach me over Discord at `@airo.pi`. Feel free to open an issue if you encounter any problem! Feel free to contribute if you see a solution.

## License

Discord M3U stream is under the MIT Licence.
